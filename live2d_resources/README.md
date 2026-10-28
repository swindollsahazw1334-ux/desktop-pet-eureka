# 把 Live2D 模型放在这里

程序不附带任何模型。把你有权使用的 Live2D Cubism 3/4 模型文件夹放进来，例如：

    live2d_resources/
        MyModel/
            MyModel.model3.json
            MyModel.moc3
            ...

没有在设置里指定模型时，会自动使用这里找到的第一个 `.model3.json`。
表情名和默认的不一样的话，在 `character.json` 的 `expression_map` 里对应一下。
