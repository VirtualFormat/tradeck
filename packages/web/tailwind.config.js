/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 深色专业终端风 design token
        term: {
          bg: '#0a0e14',
          panel: '#111823',
          border: '#1e2733',
          text: '#c5cdd6',
          muted: '#6b7684',
          up: '#2ebd85',
          down: '#f6465d',
          accent: '#4c8dff',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
