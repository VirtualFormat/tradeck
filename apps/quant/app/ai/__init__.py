"""AI 策略生成：ast 安全闸（validator）+ 轻量条件编译（conditions）+ 完整生成器（generator）。

安全模型一句话：AI 生成的代码先过 validator（纯 ast，不执行），
合格后才允许进入 strategy/ai/ 目录被 loader 加载执行；AI 未配置（AI_API_KEY 空）时
generator.enabled=False，整个功能关闭。
"""
