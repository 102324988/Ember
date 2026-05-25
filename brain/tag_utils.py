"""
标签处理工具 - 修复和处理 <thought> 标签的完整性问题
"""
import re
import logging

logger = logging.getLogger(__name__)


def fix_thought_tags(text: str) -> str:
    """
    修复不完整的 <thought> 标签

    常见问题：
    - <thought 缺少 >（LLM 流式输出被中断时最常见）
    - </thought` 或 </thought 缺少 >
    - 只有 <thought> 没有 </thought>
    - 只有 </thought> 没有 <thought>
    """
    if not text:
        return text

    original_text = text

    # 1. 修复不完整的开启标签：<thought 后面不是 > 的情况（含行尾）
    text = re.sub(r'<thought(?!>)', '<thought>', text)

    # 2. 修复不完整的闭合标签
    text = re.sub(r'</thought[`\'"]+', '</thought>', text)   # </thought` 等
    text = re.sub(r'</thought([^>])', r'</thought>\1', text) # </thought 缺少 >
    text = re.sub(r'</thought$', '</thought>', text, flags=re.MULTILINE)

    # 3. 检查标签配对
    open_tags = text.count('<thought>')
    close_tags = text.count('</thought>')

    if open_tags > close_tags:
        # 在文本末尾补充 </thought>
        text = text.rstrip() + '\n</thought>'
        logger.warning("修复了未闭合的 <thought> 标签")

    elif close_tags > open_tags:
        # 在文本开头补充 <thought>
        text = '<thought>\n' + text
        logger.warning("修复了未开启的 </thought> 标签")

    if text != original_text:
        logger.info(f"标签修复前: {original_text[:100]}...")
        logger.info(f"标签修复后: {text[:100]}...")

    return text


def remove_thought_content(text: str) -> str:
    """
    移除 <thought>...</thought> 标签及其内容
    支持不完整的标签（容错处理）
    
    Args:
        text: 原始文本
        
    Returns:
        移除 thought 内容后的文本
    """
    if not text:
        return text
    
    # 先修复标签
    text = fix_thought_tags(text)
    
    # 移除完整的 thought 块
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    
    # 清理可能残留的不完整标签
    text = re.sub(r'</?thought[^>]*>', '', text)
    
    # 清理多余的空行
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text


def extract_thought_and_speech(text: str) -> tuple[str, str]:
    """
    分离 thought 内容和 speech 内容
    
    Args:
        text: 原始文本
        
    Returns:
        (thought_content, speech_content)
    """
    if not text:
        return "", ""
    
    # 先修复标签
    text = fix_thought_tags(text)
    
    # 提取 thought 内容
    thought_match = re.search(r'<thought>([\s\S]*?)</thought>', text)
    thought = thought_match.group(1).strip() if thought_match else ""
    
    # 提取 speech 内容（移除 thought 部分）
    speech = remove_thought_content(text)
    
    return thought, speech


def validate_and_fix_llm_output(text: str) -> str:
    """
    验证并修复 LLM 输出的格式问题
    主要用于在保存到数据库前进行格式校验

    Args:
        text: LLM 输出的原始文本

    Returns:
        修复后的文本
    """
    if not text:
        return text

    # 修复 thought 标签
    text = fix_thought_tags(text)

    # 修复 speech 标签
    text = fix_speech_tags(text)

    # 剥除 LLM 自行发明的 <response> 标签（保留内容）
    if '<response>' in text or '</response>' in text:
        text = re.sub(r'<response>\s*', '', text)
        text = re.sub(r'\s*</response>', '', text)
        logger.warning("剥除了多余的 <response> 标签")

    # 清理其他可能的格式问题
    # 移除多余的反引号
    text = re.sub(r'```\s*', '', text)

    # 确保不会有多余的空行
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def parse_speech_segments(text: str) -> list[dict]:
    """
    解析包含 <speech p="X" a="Y" d="Z">content</speech> 标签的文本

    将文本拆分为多个语音片段，每个片段包含 PAD 参数：
    - p: pitch（语调），1-10
    - a: arousal（情感强度），1-10
    - d: dominance（支配感），1-10

    没有被 <speech> 标签包裹的文本使用默认 PAD 值 (5, 5, 5)

    Args:
        text: 可能包含 <speech> 标签的原始文本

    Returns:
        语音片段列表，每个片段为 dict，包含 text, p, a, d 键
    """
    if not text:
        return []

    # 匹配 <speech p="X" a="Y" d="Z">content</speech> 标签
    pattern = r'<speech\s+p=["\']?(\d+)["\']?\s+a=["\']?(\d+)["\']?\s+d=["\']?(\d+)["\']?\s*>(.*?)</speech>'
    matches = list(re.finditer(pattern, text, re.DOTALL))

    # 如果没有匹配到任何 speech 标签，返回整段文本作为单个片段（使用默认 PAD 值）
    if not matches:
        stripped = text.strip()
        if stripped:
            return [{'text': stripped, 'p': 5, 'a': 5, 'd': 5}]
        return []

    segments = []
    last_end = 0

    for match in matches:
        # 处理标签前的普通文本
        before_text = text[last_end:match.start()].strip()
        if before_text:
            segments.append({'text': before_text, 'p': 5, 'a': 5, 'd': 5})

        # 提取标签内的 PAD 值并限制在 1-10 范围内
        p = max(1, min(10, int(match.group(1))))
        a = max(1, min(10, int(match.group(2))))
        d = max(1, min(10, int(match.group(3))))
        content = match.group(4).strip()

        # 跳过空内容片段
        if content:
            segments.append({'text': content, 'p': p, 'a': a, 'd': d})

        last_end = match.end()

    # 处理最后一个标签之后的普通文本
    after_text = text[last_end:].strip()
    if after_text:
        segments.append({'text': after_text, 'p': 5, 'a': 5, 'd': 5})

    return segments


def remove_speech_tags(text: str) -> str:
    """
    移除所有 <speech ...> 和 </speech> 标签，保留标签内的文本内容

    Args:
        text: 可能包含 <speech> 标签的文本

    Returns:
        移除标签后的纯文本
    """
    if not text:
        return text

    # 移除开启标签 <speech ...>
    text = re.sub(r'<speech[^>]*>', '', text)
    # 移除闭合标签 </speech>
    text = re.sub(r'</speech>', '', text)

    # 清理多余的空行
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = text.strip()

    return text


def fix_speech_tags(text: str) -> str:
    """
    修复不完整的 <speech> 标签（缺少闭合或多余闭合）

    - 如果开启标签数 > 闭合标签数，在文本末尾追加 </speech>
    - 如果闭合标签数 > 开启标签数，移除多余的 </speech>

    Args:
        text: 可能包含不完整 <speech> 标签的文本

    Returns:
        修复后的文本
    """
    if not text:
        return text

    # 统计开启和闭合标签数量
    open_tags = len(re.findall(r'<speech[^>]*>', text))
    close_tags = text.count('</speech>')

    if open_tags > close_tags:
        # 缺少闭合标签，在末尾补充
        for _ in range(open_tags - close_tags):
            text = text.rstrip() + '</speech>'
        logger.warning("修复了未闭合的 <speech> 标签")

    elif close_tags > open_tags:
        # 多余的闭合标签，从后向前移除多余的
        excess = close_tags - open_tags
        for _ in range(excess):
            # 找到最后一个 </speech> 并移除
            idx = text.rfind('</speech>')
            if idx != -1:
                text = text[:idx] + text[idx + len('</speech>'):]
        logger.warning("移除了多余的 </speech> 标签")

    return text
