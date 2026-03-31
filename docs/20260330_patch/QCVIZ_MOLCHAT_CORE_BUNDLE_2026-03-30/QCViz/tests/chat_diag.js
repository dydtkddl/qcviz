const fs = require('fs');
const code = fs.readFileSync('D:\\20260305_양자화학시각화MCP서버구축\\version03\\src\\qcviz_mcp\\web\\static\\chat.js', 'utf8');
const html = fs.readFileSync('D:\\20260305_양자화학시각화MCP서버구축\\version03\\src\\qcviz_mcp\\web\\templates\\index.html', 'utf8');

console.log('=== CHAT HISTORY DIAGNOSTIC ===');
console.log('_restoreChatHistory defined:', code.includes('function _restoreChatHistory'));
console.log('_restoreChatHistory called:', code.includes('_restoreChatHistory()'));
console.log('App.getChatMessages used:', code.includes('App.getChatMessages'));

// Script load order
var scriptIdx = html.indexOf('chat.js');
var divIdx = html.indexOf('id="chatMessages"');
console.log('chatMessages div position:', divIdx, '| chat.js position:', scriptIdx);
console.log('DIV before SCRIPT:', divIdx < scriptIdx, '(must be true)');

// Check DOMContentLoaded usage
console.log('Uses DOMContentLoaded:', code.includes('DOMContentLoaded'));

// Lookbehind regex test
try {
  var re = /(?<![*])\*([^*]+?)\*(?![*])/g;
  console.log('Lookbehind regex works:', true);
} catch(e) {
  console.log('Lookbehind regex FAILS:', e.message);
}

console.log('QCVIZ_CHAT key in HTML:', html.includes('QCVIZ_CHAT'));
console.log('getChatMessages fn in HTML:', html.includes('getChatMessages'));
