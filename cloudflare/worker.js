const CHAT = '@cf/meta/llama-3.1-8b-instruct-fp8-fast';
const EDITOR = '@cf/mistralai/mistral-small-3.1-24b-instruct';
const VISION = '@cf/meta/llama-3.2-11b-vision-instruct';
const ASR = '@cf/openai/whisper';
const VOICE = '@cf/deepgram/aura-1';
export default {
  async fetch(request, env) {
    if (!env.AUTH_TOKEN) return new Response('Not configured', {status:503});
    if (request.headers.get('Authorization') !== `Bearer ${env.AUTH_TOKEN}`)
      return new Response('Unauthorized', {status:401});
    if (request.method !== 'POST' || new URL(request.url).pathname !== '/run')
      return new Response('Not found', {status:404});
    const raw = await request.text();
    if (raw.length > 600000) return new Response('Too large', {status:413});
    let data;
    try {data=JSON.parse(raw);} catch {return new Response('Bad JSON',{status:400});}
    const {model,input}=data;
    if (![CHAT,EDITOR,VOICE,VISION,ASR].includes(model) || !input) return new Response('Model denied',{status:400});
    if (model === VISION || model === ASR) {
      const bytes = model === VISION ? input.image : input.audio;
      const agreement = model === VISION && input.prompt === 'agree';
      if (!agreement && (!Array.isArray(bytes) || bytes.length > 120000 ||
          bytes.some(n => !Number.isInteger(n) || n < 0 || n > 255)))
        return new Response('Media profile denied',{status:400});
      if (model === VISION && (typeof input.prompt !== 'string' || input.prompt.length > 2500 ||
          !Number.isInteger(input.max_tokens) || input.max_tokens < 1 || input.max_tokens > 450))
        return new Response('Vision profile denied',{status:400});
      try {
        const options = model === VISION
          ? {prompt:input.prompt, ...(agreement ? {} : {image:bytes}), max_tokens:input.max_tokens, temperature:0.1}
          : {audio:bytes};
        const result = await env.AI.run(model,options);
        return Response.json({success:true,result});
      } catch(error) {return Response.json({success:false,error:String(error.message).slice(0,400)},{status:502});}
    }
    if (raw.length > 48000) return new Response('Too large',{status:413});
    if (model === CHAT || model === EDITOR) {
      if (!Array.isArray(input.messages) || input.messages.length>24 ||
          !Number.isInteger(input.max_tokens) || input.max_tokens<1 || input.max_tokens>1400)
        return new Response('Profile denied',{status:400});
      // Input never gets access to AWS, the Instagram token, or Telegram tools.
      const options = {messages:input.messages, max_tokens:input.max_tokens, temperature:0.2};
      if (input.tools) {
        if (!Array.isArray(input.tools) || input.tools.length > 12) return new Response('Tools profile denied',{status:400});
        options.tools = input.tools.map(tool => ({type:"function",function:tool}));
      } else options.response_format = {type:'json_object'};
      let result;
      try { result = await env.AI.run(model, options); }
      catch (error) { return Response.json({success:false,error:String(error.message).slice(0,400)},{status:502}); }
      return Response.json({success:true,result});
    }
    if (typeof input.text!=='string' || input.text.length>600 || /[^\x00-\x7f]/.test(input.text))
      return new Response('Voice profile denied',{status:400});
    const speaker = input.speaker || 'orion';
    if (!['orion','arcas','angus','orpheus','perseus','helios','zeus'].includes(speaker))
      return new Response('Speaker denied',{status:400});
    const audio = await env.AI.run(VOICE, {
      text:input.text, speaker, encoding:'linear16',container:'wav',sample_rate:24000
    });
    return new Response(audio, {headers:{'Content-Type':'audio/wav','Cache-Control':'no-store'}});
  }
};
