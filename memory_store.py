"""
尤里卡的长期记忆 (参考 Mem0 的经典做法，自己实现)

每聊完一轮，在后台做三件事：
    1. 提炼：让大模型从这轮对话里挑出值得长期记住的事实 (喜好、经历、计划、家人宠物……)
    2. 比对：每条新事实去记忆库里找意思相近的旧记忆
    3. 决定：让大模型逐条判断 新增 / 更新 / 删除 / 不变，再写回记忆库
所以 "喜欢蓝色" 后来变成 "喜欢红色" 时会改掉旧的，而不是两条都留着；重复的也会合并。

存储：本地 ChromaDB (eureka_memory_db/)，向量用百炼中文向量模型 text-embedding-v4，
大模型用脑子同一个 (VOLC_MODEL_NAME)，Key 也共用。数据只存在本机。
"""
import json
import os
import re
import sys
import threading
import time
import uuid

from dotenv import load_dotenv
from openai import OpenAI

import character
import notify
import usage


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(get_app_path(), ".env"))


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return default if not value or value.startswith("#") else value


API_KEY = _env("VOLC_API_KEY")
BASE_URL = _env("VOLC_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = _env("MEMORY_MODEL") or _env("VOLC_MODEL_NAME", "qwen-plus")
EMBED_MODEL = _env("MEMORY_EMBED_MODEL", "text-embedding-v4")
EMBED_DIMS = 1024
DB_PATH = os.path.join(get_app_path(), "eureka_memory_db")

SEARCH_MIN_SIMILARITY = 0.35   # 相似度低于这个的记忆不拿给大模型看，免得塞进不相干的
MATCH_TOP_K = 5                # 每条新事实拿几条相近旧记忆去比对

EXTRACT_PROMPT = """你是记忆整理员，负责从对话里提炼值得长期记住的、关于用户本人的事实。

只提炼这些：用户的喜好和厌恶、个人信息（工作、学校、住处、作息）、家人朋友和宠物、重要经历、计划和约定、对尤里卡的要求和习惯。
不要提炼：寒暄、一次性的指令（比如"把音量调到30"、"放首歌"）、天气和新闻等客观信息、尤里卡自己说的话、猜测。

每条事实用简短中文陈述句，不带主语"用户"，例如："喜欢蓝色"、"养了一只叫鸭蛋的猫"、"下周五要考驾照科目二"。
没有值得记的就返回空列表。

另外，如果用户提到了将来某天要做的具体事情 (面试、考试、出差、约会、看病……)，
再把它放进 plans，日期换算成 YYYY-MM-DD (今天的日期会给你)；说不清哪天的就不要放。

只输出 JSON：{"facts": ["...", "..."], "plans": [{"event": "面试", "date": "2026-10-30"}]}"""

DECIDE_PROMPT = """你是记忆管理员。下面是已有的旧记忆 (带编号) 和刚提炼出的新事实，请决定怎么更新记忆库。

对每条旧记忆和新事实，给出一种操作：
- ADD：新事实是新的信息，旧记忆里没有 → 新增 (id 写 "new")
- UPDATE：新事实和某条旧记忆说的是同一件事，但信息变了或更完整 → 用新内容替换那条旧记忆 (id 写旧记忆编号)
  例：旧 "喜欢蓝色"，新 "现在更喜欢红色了" → UPDATE 为 "喜欢红色 (以前喜欢蓝色)"
  例：旧 "养了一只猫"，新 "猫叫鸭蛋" → UPDATE 为 "养了一只叫鸭蛋的猫"
- DELETE：新事实明确否定了某条旧记忆 → 删除那条 (id 写旧记忆编号)
- NONE：旧记忆不受影响，或新事实和旧记忆意思重复 → 不变

只能使用给出的旧记忆编号，不要编造编号。只输出 JSON：
{"memory": [{"id": "0", "text": "记忆内容", "event": "ADD|UPDATE|DELETE|NONE"}, ...]}"""


class MemoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._collection = None

    # ---------------- 底层 ----------------
    @property
    def client(self):
        if self._client is None:
            self._client = usage.TrackedClient(OpenAI(api_key=API_KEY, base_url=BASE_URL))
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings
            db = chromadb.PersistentClient(path=DB_PATH, settings=Settings(anonymized_telemetry=False))
            self._collection = db.get_or_create_collection("facts", metadata={"hnsw:space": "cosine"})
        return self._collection

    def _embed(self, texts):
        vectors = []
        for i in range(0, len(texts), 10):  # 百炼向量接口一次最多 10 条
            resp = self.client.embeddings.create(model=EMBED_MODEL, input=texts[i:i + 10],
                                                 dimensions=EMBED_DIMS, encoding_format="float")
            vectors += [d.embedding for d in resp.data]
        return vectors

    def _ask_json(self, system, user):
        resp = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        text = resp.choices[0].message.content or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group()) if m else {}

    # ---------------- 写入 ----------------
    def add_turn(self, user_name, user_text, reply_text):
        """一轮对话结束后调用 (会调大模型，放后台线程里跑)"""
        if not API_KEY or not user_name or not (user_text or "").strip():
            return
        try:
            today = time.strftime("%Y-%m-%d") + " 星期" + "一二三四五六日"[time.localtime().tm_wday]
            conversation = f"今天是 {today}。\n用户（{user_name}）：{user_text}\n{character.name()}：{reply_text}"
            extracted = self._ask_json(EXTRACT_PROMPT, conversation)
            plans = [p for p in (extracted.get("plans") or []) if isinstance(p, dict)]
            if plans and on_plans:
                on_plans(user_name, plans)
            facts = extracted.get("facts") or []
            facts = [f.strip() for f in facts if isinstance(f, str) and f.strip()]
            if facts:
                self._merge(user_name, facts)
        except Exception as e:
            notify.report(e, "整理记忆")

    def remember(self, user_name, fact):
        """用户明确要求记住的事 (remember 工具)，跳过提炼，直接和旧记忆比对合并"""
        if not API_KEY or not user_name or not (fact or "").strip():
            return
        try:
            self._merge(user_name, [fact.strip()])
        except Exception as e:
            notify.report(e, "写入记忆")

    def _merge(self, user_name, facts):
        with self._lock:
            fact_vectors = self._embed(facts)

            # 找出和这些新事实相近的旧记忆
            old = {}
            for vec in fact_vectors:
                for mem in self._query(user_name, vec, MATCH_TOP_K):
                    old.setdefault(mem["id"], mem["text"])
            # 用临时编号代替真实 ID，免得大模型抄错或编造 ID
            temp_ids = {str(i): real_id for i, real_id in enumerate(old)}
            old_list = [{"id": tid, "text": old[rid]} for tid, rid in temp_ids.items()]

            decision = self._ask_json(DECIDE_PROMPT, json.dumps(
                {"旧记忆": old_list, "新事实": facts}, ensure_ascii=False))

            now = time.time()
            # 一字不差的重复内容不再新增 (同一批里重复、或库里已经有)
            existing = set(self.collection.get(where={"user": user_name})["documents"]) if self.collection.count() else set()
            for item in decision.get("memory") or []:
                event = str(item.get("event", "")).upper()
                text = str(item.get("text", "")).strip()
                real_id = temp_ids.get(str(item.get("id")))
                if event == "ADD" and text and text not in existing:
                    existing.add(text)
                    self.collection.add(ids=[str(uuid.uuid4())], documents=[text], embeddings=self._embed([text]),
                                        metadatas=[{"user": user_name, "created_at": now, "updated_at": now}])
                    print(f"   🧠 [记住了] {text}")
                elif event == "UPDATE" and text and real_id:
                    created = self.collection.get(ids=[real_id])["metadatas"]
                    created_at = created[0].get("created_at", now) if created else now
                    self.collection.update(ids=[real_id], documents=[text], embeddings=self._embed([text]),
                                           metadatas=[{"user": user_name, "created_at": created_at, "updated_at": now}])
                    print(f"   🧠 [更新记忆] {old.get(real_id)} → {text}")
                elif event == "DELETE" and real_id:
                    self.collection.delete(ids=[real_id])
                    print(f"   🧠 [忘掉了] {old.get(real_id)}")

    # ---------------- 读取 ----------------
    def _query(self, user_name, vector, top_k):
        if self.collection.count() == 0:
            return []
        res = self.collection.query(query_embeddings=[vector], n_results=top_k, where={"user": user_name})
        return [{"id": i, "text": d, "similarity": 1 - dist}
                for i, d, dist in zip(res["ids"][0], res["documents"][0], res["distances"][0])]

    def search(self, user_name, query, top_k=8):
        """和当前话题相关的记忆 (相似度够高的才要)"""
        if not API_KEY or not query:
            return []
        try:
            with self._lock:
                hits = self._query(user_name, self._embed([query])[0], top_k)
            return [h["text"] for h in hits if h["similarity"] >= SEARCH_MIN_SIMILARITY]
        except Exception as e:
            print(f"   ⚠️ 检索记忆失败: {e}")
            return []

    def recent(self, user_name, limit=20):
        """最近更新的记忆 (不需要联网)"""
        try:
            with self._lock:
                res = self.collection.get(where={"user": user_name})
            items = sorted(zip(res["documents"], res["metadatas"]),
                           key=lambda x: x[1].get("updated_at", 0), reverse=True)
            return [doc for doc, _ in items[:limit]]
        except Exception as e:
            print(f"   ⚠️ 读取记忆失败: {e}")
            return []

    def old_facts(self, user_name, min_age_days=7):
        """一段时间以前记下的事 [(内容, 几天前)]，给 "还记得吗" 的回忆用"""
        try:
            with self._lock:
                res = self.collection.get(where={"user": user_name})
            now = time.time()
            return [(doc, int((now - meta.get("created_at", now)) / 86400))
                    for doc, meta in zip(res["documents"], res["metadatas"])
                    if now - meta.get("created_at", now) >= min_age_days * 86400]
        except Exception:
            return []

    def count(self, user_name=None):
        try:
            if user_name:
                return len(self.collection.get(where={"user": user_name})["ids"])
            return self.collection.count()
        except Exception:
            return 0

    def context_for(self, user_name, query=None, recent_limit=10):
        """
        给提示词用的记忆文字：记忆不多就全给；多了就给 "和当前话题相关的" + "最近的"
        """
        if self.count(user_name) <= 30:
            facts = self.recent(user_name, limit=30)
        else:
            facts = self.search(user_name, query) if query else []
            facts += [f for f in self.recent(user_name, recent_limit) if f not in facts]
        return "；".join(facts)

    # ---------------- 迁移 ----------------
    def migrate_old_profiles(self, user_profiles):
        """把 memory.json 里 user_profiles 的旧事实搬过来 (会顺便合并重复的)，只做一次"""
        marker = os.path.join(DB_PATH, ".migrated")
        if os.path.exists(marker) or not API_KEY or not user_profiles:
            return
        print("   📦 正在把旧档案搬进新的记忆库...")
        for user_name, facts in user_profiles.items():
            facts = [f for f in facts if isinstance(f, str) and f.strip()]
            for i in range(0, len(facts), 8):
                self._merge(user_name, facts[i:i + 8])
        os.makedirs(DB_PATH, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        print("   📦 旧档案搬家完成")


store = MemoryStore()
on_plans = None  # 提取出带日期的计划时回调 (陪伴模块用来到点追问)


def add_turn_async(user_name, user_text, reply_text):
    threading.Thread(target=store.add_turn, args=(user_name, user_text, reply_text), daemon=True).start()


def remember_async(user_name, fact):
    threading.Thread(target=store.remember, args=(user_name, fact), daemon=True).start()
