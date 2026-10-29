const CHAT = '@cf/meta/llama-3.1-8b-instruct-fp8-fast';
const EDITOR = '@cf/mistralai/mistral-small-3.1-24b-instruct';
const VOICE = '@cf/deepgram/aura-1';
export default {
  async fetch(request, env) {
    if (!env.AUTH_TOKEN) return new Response('Not configured', {status:503});
    if (request.headers.get('Authorization') !== `Bearer ${env.AUTH_TOKEN}`)
      return new Response('Unauthorized', {status:401});
    if (request.method !== 'POST' || new URL(request.url).pathname !== '/run')
      return new Response('Not found', {status:404});
    const raw = await request.text();
    if (raw.length > 22000) return new Response('Too large', {status:413});
    let data;
    try {data=JSON.parse(raw);} catch {return new Response('Bad JSON',{status:400});}
    const {model,input}=data;
    if (![CHAT,EDITOR,VOICE].includes(model) || !input) return new Response('Model denied',{status:400});
    if (model === CHAT || model === EDITOR) {
      if (!Array.isArray(input.messages) || input.messages.length>12 ||
          !Number.isInteger(input.max_tokens) || input.max_tokens<1 || input.max_tokens>1400)
        return new Response('Profile denied',{status:400});
      // Input never gets access to AWS, the Instagram token, or Telegram tools.
      const result = await env.AI.run(model, {
        messages:input.messages, max_tokens:input.max_tokens,
        temperature:0.35, response_format:{type:'json_object'}
      });
      return Response.json({success:true,result});
    }
    if (typeof input.text!=='string' || input.text.length>600 || /[^\x00-\x7f]/.test(input.text))
      return new Response('Voice profile denied',{status:400});
    const audio = await env.AI.run(VOICE, {
      text:input.text, speaker:'asteria', encoding:'linear16',container:'wav',sample_rate:24000
    });
    return new Response(audio, {headers:{'Content-Type':'audio/wav','Cache-Control':'no-store'}});
  }
};
