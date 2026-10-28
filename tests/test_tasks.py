import tasks


def make_board(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "TASKS_FILE", str(tmp_path / "tasks.json"))
    board = tasks.TaskBoard()
    monkeypatch.setattr(board, "_notify", lambda user: None)
    return board


def test_add_skips_duplicates_and_blanks(tmp_path, monkeypatch):
    board = make_board(tmp_path, monkeypatch)
    assert board.add("小明", ["写周报", "写周报", "  ", "改登录页bug"]) == ["写周报", "改登录页bug"]
    assert board.progress("小明") == (0, 2)


def test_complete_matches_loosely_and_undo(tmp_path, monkeypatch):
    board = make_board(tmp_path, monkeypatch)
    board.add("小明", ["写周报", "回邮件"])
    assert board.complete("小明", "周报")["text"] == "写周报"
    assert board.progress("小明") == (1, 2)
    assert board.unfinished("小明") == ["回邮件"]
    board.undo("小明", "周报")
    assert board.progress("小明") == (0, 2)


def test_tasks_survive_reload(tmp_path, monkeypatch):
    make_board(tmp_path, monkeypatch).add("小明", ["写周报"])
    assert [t["text"] for t in tasks.TaskBoard().items("小明")] == ["写周报"]


def test_users_are_separate(tmp_path, monkeypatch):
    board = make_board(tmp_path, monkeypatch)
    board.add("小明", ["写周报"])
    assert board.describe("小红") == "今天还没列任务"
