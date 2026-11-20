import html
import re

LINK_PATTERN = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
FORMATTING = (
    (re.compile(r'\*\*([^*\n]+)\*\*'), 'b'),
    (re.compile(r'__([^_\n]+)__'), 'u'),
    (re.compile(r'~~([^~\n]+)~~'), 's'),
    (re.compile(r'`([^`\n]+)`'), 'code'),
    (re.compile(r'(?<!\*)\*([^*\n]+)\*(?!\*)'), 'i'),
)


def _inline(text):
    value = html.escape(text, quote=False)
    value = LINK_PATTERN.sub(
        lambda match: (
            f'<a href="{html.escape(match.group(2), quote=True)}">'
            f'{match.group(1)}</a>'
        ),
        value,
    )
    for pattern, tag in FORMATTING:
        value = pattern.sub(f'<{tag}>\\1</{tag}>', value)
    return value


def render_news_markdown(text, telegram=False):
    output = []
    paragraph = []
    list_items = []
    quote = []

    def flush_paragraph():
        if paragraph:
            content = '<br>'.join(_inline(line) for line in paragraph)
            output.append(content if telegram else f'<p>{content}</p>')
            paragraph.clear()

    def flush_list():
        if list_items:
            if telegram:
                output.extend(f'• {_inline(item)}' for item in list_items)
            else:
                items = ''.join(f'<li>{_inline(item)}</li>' for item in list_items)
                output.append(f'<ul>{items}</ul>')
            list_items.clear()

    def flush_quote():
        if quote:
            content = '<br>'.join(_inline(line) for line in quote)
            output.append(f'<blockquote>{content}</blockquote>')
            quote.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('- '):
            flush_paragraph()
            flush_quote()
            list_items.append(stripped[2:].strip())
            continue
        if stripped.startswith('> '):
            flush_paragraph()
            flush_list()
            quote.append(stripped[2:].strip())
            continue
        flush_list()
        flush_quote()
        if not stripped:
            flush_paragraph()
        elif stripped == '---':
            flush_paragraph()
            output.append('\n' if telegram else '<hr>')
        elif stripped.startswith('#'):
            flush_paragraph()
            heading = stripped.lstrip('#').strip()
            output.append(f'<b>{_inline(heading)}</b>' if telegram else f'<h2>{_inline(heading)}</h2>')
        else:
            paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    flush_quote()
    separator = '\n\n' if telegram else ''
    return separator.join(output)


def telegram_news_text(post, max_source_length=2800):
    content = post['content'].strip()
    if len(content) > max_source_length:
        content = content[:max_source_length].rsplit('\n', 1)[0].rstrip() + '\n…'
    title = html.escape(post['title'], quote=False)
    return f'<b>{title}</b>\n\n{render_news_markdown(content, telegram=True)}'
