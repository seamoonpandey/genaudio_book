export function chunkSentences(text: string, maxChars = 400): string[] {
  const sentences = text.split(/(?<=[.!?”"])\s+/);
  const chunks: string[] = [];
  let cur = "";
  for (let s of sentences) {
    s = s.trim();
    if (!s) continue;
    while (s.length > maxChars) {
      chunks.push(s.slice(0, maxChars));
      s = s.slice(maxChars);
    }
    if (cur.length + s.length + 1 > maxChars && cur) {
      chunks.push(cur);
      cur = s;
    } else {
      cur = cur ? `${cur} ${s}` : s;
    }
  }
  if (cur) chunks.push(cur);
  return chunks;
}
