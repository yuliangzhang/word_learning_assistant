// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  retries: 0,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8000",
    headless: true,
  },
  reporter: [["list"]],
});
