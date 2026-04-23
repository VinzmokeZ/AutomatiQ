(function() {
    if (window._zenTelemetryLoaded) return;
    window._zenTelemetryLoaded = true;

    const isIframe = window !== window.top;

    function sendAction(payload) {
        if (!window.sendActionToPython) return;
        payload.url = window.location.href;
        payload.title = document.title;
        payload.is_iframe = isIframe;
        window.sendActionToPython(JSON.stringify(payload));
    }

    sendAction({type: 'script_loaded', text: 'Telemetry script initialized'});

    // 1. Track Every Keypress
    document.addEventListener('keydown', (e) => {
        if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) return;
        sendAction({
            type: 'keypress',
            key: e.key,
            code: e.code,
            tag: e.target.tagName,
            value: e.target.value || ''
        });
    }, true);

    // 2. Track Clicks
    document.addEventListener('mousedown', (e) => {
        let target = e.target.closest('button, a, input, select, [role="button"]');
        if (!target) return;
        sendAction({
            type: 'click',
            tag: target.tagName,
            text: (target.innerText || target.value || '').substring(0, 100),
            id: target.id || '',
            href: target.href || ''
        });
    }, true);

    // 3. Track Input Changes
    document.addEventListener('change', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            sendAction({
                type: 'input',
                tag: e.target.tagName,
                name: e.target.name || e.target.id || '',
                value: e.target.value
            });
        }
    }, true);

    // 4. Track Page Changes (SPA & Hash changes)
    let lastUrl = location.href;
    new MutationObserver(() => {
        if (location.href !== lastUrl) {
            lastUrl = location.href;
            sendAction({type: 'page_changed', newUrl: location.href, reason: 'mutation'});
        }
    }).observe(document, {subtree: true, childList: true});

    window.addEventListener('popstate', () => {
        lastUrl = location.href;
        sendAction({type: 'page_changed', newUrl: location.href, reason: 'popstate'});
    });

    window.addEventListener('hashchange', () => {
        lastUrl = location.href;
        sendAction({type: 'page_changed', newUrl: location.href, reason: 'hashchange'});
    });

    // 5. Track Tabs/Windows Opened by JS
    const originalOpen = window.open;
    window.open = function(url, targetName, windowFeatures) {
        sendAction({
            type: 'window_opened',
            target_url: url,
            target_name: targetName
        });
        return originalOpen.apply(this, arguments);
    };
})();
