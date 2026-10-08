def generate_ai_prompt(query, output_filename="generated_prompt.md"):
    """
    极速版 Prompt 生成函数：减少系统调用，优化字符串处理。
    """
    # 预定义模板，减少运行时计算
    content = (
        f"# AI 查询指令：{query}\n\n"
        f"## 角色设定\n你是一位在 **{query}** 领域的资深专家。\n\n"
        f"## 任务目标\n请针对以下主题提供分析和见解：**{query}**\n\n"
        "## 回复要求\n1. **系统性**：请从基础概念、核心原理、应用场景三个维度进行阐述。\n"
        "2. **结构化**：使用清晰的标题、列表和加粗关键词，确保内容易于阅读。\n"
        "3. **批判性**：不仅要说明优点，也要分析该事物目前面临的局限性或挑战。\n"
        "4. **实用性**：如果适用，请提供 2-3 个具体的实践建议或案例研究。\n\n"
        "## 语言风格\n专业、严谨且富有启发性。"
    )

    # 使用 utf-8 编码直接写入，不进行多余的路径检查
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    # 示例用法：直接调用函数，减少交互开销
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else input("请输入查询事物: ")
    if topic:
        generate_ai_prompt(topic)
