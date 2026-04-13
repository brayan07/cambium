import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Note: StrictMode intentionally omitted — it double-mounts effects in dev,
// which breaks WebSocket and PTY lifecycle management.
createRoot(document.getElementById('root')!).render(<App />)
