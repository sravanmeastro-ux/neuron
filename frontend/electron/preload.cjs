const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("neuronDesktop", {
  onConfig: (cb) => ipcRenderer.on("neuron-config", (_e, data) => cb(data)),
});
