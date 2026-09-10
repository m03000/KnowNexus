/** 读取 POST 请求返回的 SSE 字节流，并逐条交给调用方。 */
export async function consumeSse(response, onEvent) {
  if (!response.body) throw new Error('当前浏览器不支持流式响应');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const dispatchFrame = (frame) => {
    let eventName = 'message';
    const dataLines = [];
    frame.split(/\r?\n/).forEach((line) => {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    });
    if (dataLines.length) onEvent(eventName, JSON.parse(dataLines.join('\n')));
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || '';

    for (const frame of frames) {
      dispatchFrame(frame);
    }
    if (done) {
      if (buffer.trim()) dispatchFrame(buffer);
      break;
    }
  }
}
