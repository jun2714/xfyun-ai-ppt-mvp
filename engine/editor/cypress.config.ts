import { defineConfig } from "cypress";

export default defineConfig({
  allowCypressEnv: false,
  component: {
    // Component specs in this repository mount their own providers/router and do
    // not rely on a global Cypress support file. Being explicit keeps clean CI
    // checkouts from failing before the first spec is loaded.
    supportFile: false,
    indexHtmlFile: "cypress/support/component-index.html",
    specPattern: "app/**/*.cy.{js,jsx,ts,tsx}",
    devServer: {
      framework: "next",
      bundler: "webpack",
    },
  },
});
