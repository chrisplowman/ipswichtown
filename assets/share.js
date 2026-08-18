// Adds a "share this card as an image" button next to every card's existing
// info icon, so every card gets one without hand-editing each template block.
// Renders the card with html2canvas, then hands the PNG to the native share
// sheet (mobile/modern browsers) or falls back to a plain download.
(function(){
  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" '
    + 'stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4"/>'
    + '<path d="M7.5 8.5 12 4l4.5 4.5"/>'
    + '<path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/></svg>';

  function slug(s){
    return (s || 'card').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'card';
  }
  function titleFor(head){
    var t = head.querySelector('h3, .snapshot-label, .fg-label');
    return t ? t.textContent.trim() : 'Ipswich Town';
  }
  function cardFor(head){
    return head.closest('.card, .chartcard, .snapshot, .survival, .formguide') || head.parentElement;
  }
  // Races a promise against a plain timer so a slow/blocked network resource
  // (e.g. the Google Fonts stylesheet) can't hang document.fonts.ready, and
  // therefore the share button, indefinitely.
  function withTimeout(promise, ms){
    return Promise.race([promise, new Promise(function(resolve){ setTimeout(resolve, ms); })]);
  }

  async function renderAndShare(card, title){
    if(document.fonts && document.fonts.ready){ await withTimeout(document.fonts.ready, 3000); }
    var canvas = await html2canvas(card, {
      backgroundColor: getComputedStyle(card).backgroundColor || '#ffffff',
      scale: Math.min(2, window.devicePixelRatio || 1.5),
      useCORS: true,
      // Badge images come from an external CDN with no guaranteed CORS headers;
      // don't let one slow/blocked image stall the whole export for 15s+ (the
      // default) — a missing crest just renders blank, which is fine here.
      imageTimeout: 4000,
      ignoreElements: function(el){ return el.classList && el.classList.contains('cardactions'); }
    });
    await new Promise(function(resolve){
      canvas.toBlob(function(blob){
        if(!blob){ resolve(); return; }
        var file = new File([blob], 'ipswich-town-' + slug(title) + '.png', {type: 'image/png'});
        if(navigator.canShare && navigator.canShare({files: [file]})){
          navigator.share({files: [file], title: title + ' · Ipswich Town'}).catch(function(){}).then(resolve);
        } else {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = file.name;
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function(){ URL.revokeObjectURL(a.href); }, 4000);
          resolve();
        }
      }, 'image/png');
    });
  }

  async function shareCard(card, title, btn){
    if(!window.html2canvas){ return; }
    btn.classList.add('busy');
    try{
      // A hard ceiling on the whole pipeline: html2canvas's own document-clone
      // step can otherwise hang far longer than imageTimeout covers if a
      // linked stylesheet (e.g. Google Fonts) is unreachable rather than just
      // missing an image, leaving the button stuck forever.
      await Promise.race([
        renderAndShare(card, title),
        new Promise(function(_, reject){ setTimeout(function(){ reject(new Error('share timed out')); }, 20000); })
      ]);
    } catch(e){
      console.error('Card share failed', e);
    } finally {
      btn.classList.remove('busy');
    }
  }

  document.querySelectorAll('.cardhead, .fg-head').forEach(function(head){
    if(head.querySelector('.sharebtn')) return;
    var info = head.querySelector('.infobtn');

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sharebtn';
    btn.setAttribute('aria-label', 'Share this card as an image');
    btn.innerHTML = ICON;
    btn.addEventListener('click', function(){
      shareCard(cardFor(head), titleFor(head), btn);
    });

    var actions = document.createElement('div');
    actions.className = 'cardactions';
    if(info){
      info.parentNode.insertBefore(actions, info);
      actions.appendChild(btn);
      actions.appendChild(info);
    } else {
      actions.appendChild(btn);
      head.appendChild(actions);
    }
  });
})();
