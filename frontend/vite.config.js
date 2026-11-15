import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// npm run dev        -> http://localhost:5173 (laptop; the mic works on localhost)
// npm run dev:phone  -> https://<laptop-ip>:5173 with a self-signed certificate, so a phone on the same
//                       Wi-Fi can use the mic (browsers only allow the mic on https or localhost)
//
// The browser calls /api/... and Vite forwards it to FastAPI on port 8000, so the phone only needs
// to reach this one address. (LiveKit audio goes straight to LiveKit Cloud.)
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'phone' ? [basicSsl()] : [])],
  server: {
    host: mode === 'phone' ? true : 'localhost',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
}))
