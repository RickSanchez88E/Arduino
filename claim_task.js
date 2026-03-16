const { spawn } = require('child_process');

const args = ['run', '@djmax/mcp-graph', '--', '--method', 'graph_onboard', '--params', JSON.stringify({
  project_name: 'geo-survivor',
  onboard_mode: 'continue'
})];

const proc = spawn('npx', ['-y', '@smithery/cli', ...args], { stdio: 'pipe' });

proc.stdout.on('data', data => console.log(data.toString()));
proc.stderr.on('data', data => console.error(data.toString()));
proc.on('close', code => console.log(`child process exited with code ${code}`));
