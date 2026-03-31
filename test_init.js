const fs = require('fs');

const code = fs.readFileSync('version02/src/qcviz_mcp/web/static/viewer.js', 'utf8');

// evaluate init function via a mock to see if anything throws
const mockEnv = `
var window = { matchMedia: function() { return { matches: false }; }, QCVizApp: { clone: function(x){return x;}, getUISnapshot: function(){return null;}, saveUISnapshot: function(){}, on: function(){}, store: {activeJobId: null}, emit: function(){} } };
var document = { 
  documentElement: { getAttribute: function() { return "light"; } },
  body: { classList: { contains: function() { return false; } } },
  getElementById: function(id) { 
    return { 
      addEventListener: function() {}, 
      classList: { toggle: function() {}, remove: function() {}, add: function() {} },
      querySelector: function() { return { style: {} }; },
      querySelectorAll: function() { return []; },
      setAttribute: function() {},
      appendChild: function() {},
      style: {}
    }; 
  },
  createElement: function() { return {}; },
  addEventListener: function() {}
};
var App = window.QCVizApp;
`;

try {
  eval(mockEnv + code);
  console.log("Evaluation successful");
} catch(e) {
  console.log("Eval error:", e);
}
