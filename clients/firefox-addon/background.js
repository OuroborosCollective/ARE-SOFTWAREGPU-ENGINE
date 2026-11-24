"use strict";

browser.action.onClicked.addListener(() => {
  browser.tabs.create({ url: browser.runtime.getURL("diagnostics.html") }).catch(console.error);
});
