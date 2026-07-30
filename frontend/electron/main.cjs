const { app, BrowserWindow } = require("electron");
const path = require("path");

const BRAIN = process.env.NEURON_BRAIN || "http://127.0.0.1:8765";

function createWindow() {
  const win = new BrowserWindow({
    width: 640,
    height: 480,
    title: "N.E.U.R.O.N",
    backgroundColor: "#05070c",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const devUrl = process.env.NEURON_DEV_URL || "http://127.0.0.1:5173";
  if (!app.isPackaged) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  win.webContents.on("did-finish-load", () => {
    win.webContents.send("neuron-config", { brain: BRAIN });
  });
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
