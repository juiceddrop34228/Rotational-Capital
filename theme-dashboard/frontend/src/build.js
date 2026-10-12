// Recompiles src/app.jsx into plain JS and writes it into ../index.html using a template.
// Usage: cd frontend/src && node build.js
const babel = require("@babel/core");
const fs = require("fs");
const path = require("path");

const jsxPath = path.join(__dirname, "app.jsx");
const indexPath = path.join(__dirname, "..", "index.html");
const templatePath = path.join(__dirname, "..", "index.template.html");

const src = fs.readFileSync(jsxPath, "utf8");
const compiled = babel.transformSync(src, {
  presets: [["@babel/preset-react", { runtime: "classic" }]],
  filename: "app.jsx",
}).code;

const template = fs.readFileSync(templatePath, "utf8");
const html = template.replace("<!-- APP_SCRIPT -->", compiled);

fs.writeFileSync(indexPath, html);
console.log("Rebuilt", indexPath, "(", compiled.length, "chars of compiled JS )");
