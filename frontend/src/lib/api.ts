// 本文件保留为 barrel 入口，避免 24+ 调用方改动 import 路径。
// 真实实现已按域拆分到 ./api/*，由 ./api/index 统一 re-export。
export * from "./api/index";
