import DefaultTheme from "vitepress/theme";
import type { Theme } from "vitepress";
import "./custom.css";
import { setupWebMcp } from "./webmcp";

const theme: Theme = {
  extends: DefaultTheme,
  enhanceApp() {
    // 浏览器端注册 WebMCP 工具（无 modelContext 时静默跳过）
    if (typeof window !== "undefined") {
      setupWebMcp();
    }
  },
};

export default theme;
