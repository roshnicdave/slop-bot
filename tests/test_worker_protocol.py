"""Exercise the actual Worker provider payload with a fake AI binding."""

import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node is needed for Worker checks")
class WorkerProtocolTests(unittest.TestCase):
    def test_plain_notifications_and_structured_plans_use_distinct_formats(self):
        source = Path(__file__).resolve().parents[1] / "cloudflare" / "worker.js"
        script = r"""
const fs = require('node:fs');
(async () => {
  const worker = (await import('data:text/javascript;base64,' +
    fs.readFileSync(process.argv[1]).toString('base64'))).default;
  let sent;
  const env = {AUTH_TOKEN:'test', AI:{run:async (model,input)=>{
    sent=input; return {response:'Ready.'};
  }}};
  for (const structured of [false,true]) {
    const input={messages:[{role:'user',content:'Report status'}],max_tokens:180};
    if (structured) input.response_format={type:'json_object'};
    const response=await worker.fetch(new Request('https://test/run',{
      method:'POST',headers:{Authorization:'Bearer test'},
      body:JSON.stringify({model:'@cf/qwen/qwen3-30b-a3b-fp8',input})
    }),env);
    if(response.status!==200) throw new Error('Request rejected');
    if('tools' in sent) throw new Error('Empty tools reached provider');
    if(structured !== ('response_format' in sent)) throw new Error('Wrong format');
  }
})().catch(error=>{console.error(error);process.exit(1)});
"""
        subprocess.run(
            ["node", "-e", script, str(source)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
