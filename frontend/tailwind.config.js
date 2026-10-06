/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9eaff",
          500: "#2563eb",
          600: "#1d4ed8",
          700: "#1e40af",
          900: "#1e3a8a",
        },
        bay: {
          free: "#dcfce7",
          allotted: "#fef3c7",
          occupied: "#e2e8f0",
          blocked: "#fee2e2",
          unknown: "#e9d5ff",
        },
      },
      boxShadow: {
        card: "0 1px 3px rgba(15, 23, 42, 0.12), 0 1px 2px rgba(15, 23, 42, 0.06)",
      },
    },
  },
  plugins: [],
};
