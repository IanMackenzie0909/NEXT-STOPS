import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        muted: "#6B7280",
        soft: "#F6FAF7",
        wellness: "#A7C4B5",
        mist: "#DDEFE5",
        lavender: "#A78BFA",
        indigo: "#6366F1"
      },
      boxShadow: {
        calm: "0 18px 45px rgba(31, 41, 55, 0.10)",
        float: "0 24px 70px rgba(99, 102, 241, 0.18)"
      },
      borderRadius: {
        app: "28px"
      }
    }
  },
  plugins: []
};
export default config;
