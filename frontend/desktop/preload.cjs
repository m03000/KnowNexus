const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', Object.freeze({
  isDesktop: true,
  apiBase: 'http://127.0.0.1:8765',
  pickFile: () => ipcRenderer.invoke('desktop:pick-file'),
  pickCookieFile: () => ipcRenderer.invoke('desktop:pick-cookie-file'),
  pickDirectory: () => ipcRenderer.invoke('desktop:pick-directory'),
  getWallpaper: () => ipcRenderer.invoke('desktop:get-wallpaper'),
  listWallpapers: () => ipcRenderer.invoke('desktop:list-wallpapers'),
  pickWallpaper: () => ipcRenderer.invoke('desktop:pick-wallpaper'),
  selectWallpaper: (id) => ipcRenderer.invoke('desktop:select-wallpaper', id),
  clearWallpaper: () => ipcRenderer.invoke('desktop:clear-wallpaper'),
  windowAction: (action) => ipcRenderer.invoke('desktop:window-action', action),
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-for-updates'),
  openUpdatePage: (url) => ipcRenderer.invoke('desktop:open-update-page', url),
}));

window.addEventListener('DOMContentLoaded', () => {
  document.documentElement.classList.add('electron-desktop');
});
