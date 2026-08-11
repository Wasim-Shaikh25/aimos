/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(220, 13%, 22%)',
        input: 'hsl(220, 13%, 22%)',
        ring: 'hsl(217, 91%, 60%)',
        background: 'hsl(222, 24%, 6%)',
        foreground: 'hsl(213, 20%, 94%)',
        muted: 'hsl(218, 14%, 56%)',
        'muted-foreground': 'hsl(218, 14%, 56%)',
        card: 'hsl(220, 21%, 10%)',
        'card-foreground': 'hsl(213, 20%, 94%)',
        popover: 'hsl(220, 21%, 10%)',
        'popover-foreground': 'hsl(213, 20%, 94%)',
        primary: 'hsl(217, 91%, 60%)',
        'primary-foreground': 'hsl(0, 0%, 100%)',
        secondary: 'hsl(220, 14%, 17%)',
        'secondary-foreground': 'hsl(213, 20%, 94%)',
        accent: 'hsl(220, 14%, 17%)',
        'accent-foreground': 'hsl(213, 20%, 94%)',
        destructive: 'hsl(0, 72%, 51%)',
        'destructive-foreground': 'hsl(0, 0%, 100%)',
        success: 'hsl(150, 60%, 45%)',
        'success-foreground': 'hsl(0, 0%, 100%)',
      },
      borderRadius: {
        lg: '0.75rem',
        md: '0.5rem',
        sm: '0.375rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
        pulse: 'pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}

