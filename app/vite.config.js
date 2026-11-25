import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relative base so the site works at https://<user>.github.io/<repo>/.
export default defineConfig({
  plugins: [react()],
  base: './',
})
