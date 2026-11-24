import "dotenv/config";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const localPythonPaths = [
  resolve(process.cwd(), ".venv/bin/python"),
  resolve(process.cwd(), ".venv/Scripts/python.exe"),
];

export const pythonExecutable =
  process.env.PYTHON ||
  localPythonPaths.find((path) => existsSync(path)) ||
  "python3";
