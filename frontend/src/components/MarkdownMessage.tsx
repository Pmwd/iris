import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const INLINE_URL = /^https?:\/\/[^\s<>]+$/i;
const CODE_SPLIT = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;
// Stop bare URLs before Markdown emphasis and CJK punctuation/characters.
// GFM's autolink literal otherwise swallows "**（中文）" into the href.
const BARE_URL =
  /https?:\/\/[^\s<>"'`*_~（）【】《》「」『』，。：；！？、一-鿿]+/g;

function linkifySegment(text: string): string {
  const re = new RegExp(BARE_URL.source, "g");
  return text.replace(re, (match, offset: number, whole: string) => {
    const before = whole.slice(Math.max(0, offset - 2), offset);
    if (before === "](" || before.endsWith("<")) return match;
    let url = match;
    let tail = "";
    while (url.length > 8 && ".,;:!?".includes(url[url.length - 1])) {
      tail = url[url.length - 1] + tail;
      url = url.slice(0, -1);
    }
    return `<${url}>${tail}`;
  });
}

/** Convert bare URLs to CommonMark angle autolinks, leaving code spans alone. */
export function normalizeMarkdown(markdown: string): string {
  return markdown
    .split(CODE_SPLIT)
    .map((segment) => {
      if (!segment) return segment;
      if (
        segment.startsWith("```") ||
        segment.startsWith("~~~") ||
        (segment.startsWith("`") && segment.endsWith("`"))
      ) {
        return segment;
      }
      return linkifySegment(segment);
    })
    .join("");
}

const components: Components = {
  a: (props) => (
    <a href={props.href} target="_blank" rel="noreferrer noopener">
      {props.children}
    </a>
  ),
  code: ({ className, children }) => {
    const text = typeof children === "string" ? children.trim() : "";
    // Models often wrap URLs in backticks. Render URL-shaped inline code as a
    // real link so Ctrl+click / direct click works; keep real code untouched.
    if (!className && INLINE_URL.test(text)) {
      return (
        <a
          className="inline-url"
          href={text}
          target="_blank"
          rel="noreferrer noopener"
        >
          {text}
        </a>
      );
    }
    return <code className={className}>{children}</code>;
  },
};

export function MarkdownMessage({ content }: { content: string }) {
  if (!content) return null;
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {normalizeMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}
