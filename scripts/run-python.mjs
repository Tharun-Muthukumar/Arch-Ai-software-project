import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')
const backendDir = path.join(repoRoot, 'backend')

const winPy = path.join(backendDir, '.venv', 'Scripts', 'python.exe')
const posixPy = path.join(backendDir, '.venv', 'bin', 'python')

let pythonBin = process.platform === 'win32' ? winPy : posixPy
if (!fs.existsSync(pythonBin)) {
  pythonBin = fs.existsSync(posixPy) ? posixPy : winPy
}
if (!fs.existsSync(pythonBin)) {
  pythonBin = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
}

const child = spawn(pythonBin, process.argv.slice(2), {
  cwd: backendDir,
  stdio: 'inherit',
  env: process.env,
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
  } else {
    process.exit(code ?? 0)
  }
})
