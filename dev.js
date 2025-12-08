const { spawn } = require("child_process");

function run(command, name) {
  const p = spawn("bash", ["-lc", command], { stdio: "inherit" });
  p.on("close", (code) => {
    console.log(`Process ${name} stopped with code ${code}`);
  });
  return p;
}

console.log("=== Starting CoasterCapital Dev Environment ===");

const backend = run(
  "cd backend && source .venv/bin/activate && uvicorn app.main:app --reload",
  "backend"
);

const frontend = run("cd frontend && npm run dev", "frontend");

process.on("SIGINT", () => {
  console.log("\nStopping all processes...");
  backend.kill("SIGINT");
  frontend.kill("SIGINT");
  process.exit();
});

