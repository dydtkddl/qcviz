const fs = require('fs');

const code = fs.readFileSync('version02/src/qcviz_mcp/web/static/viewer.js', 'utf8');

// I will check the ESP mode handling in tryRenderCachedOrbital and renderESP
const esp_match = code.indexOf('volscheme: createGradient(getCurrentColorScheme().espGradient');
if (esp_match !== -1) {
    console.log("createGradient is present.");
}

// And check switchVizMode 
const switch_match = code.indexOf('var grad = createGradient');
if (switch_match !== -1) {
    console.log("createGradient in switchVizMode is present.");
}
