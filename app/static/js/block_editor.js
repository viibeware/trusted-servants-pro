/* Reusable block editor.
   Usage:
     const editor = BlockEditor.mount(rootEl, {
       initial: [...sections],
       onSerialize: (json) => hiddenInput.value = json
     });
   The host form should serialize via onSerialize in its submit handler.
*/
(function () {
  const uid = () => Math.random().toString(36).slice(2, 10);

  const BLOCK_TYPES = [
    { type: 'paragraph', label: 'Text', icon: '¶' },
    { type: 'heading',   label: 'Heading', icon: 'H' },
    { type: 'image',     label: 'Image', icon: '🖼' },
    { type: 'video',     label: 'Video', icon: '▶' },
    { type: 'code',      label: 'Code', icon: '</>' },
    { type: 'callout',   label: 'Callout', icon: '⚠' },
    { type: 'list',      label: 'List', icon: '•' },
    { type: 'separator', label: 'Divider', icon: '—' },
  ];

  function blankBlock(type) {
    const d = {
      paragraph: { md: '' },
      heading: { level: 3, text: '' },
      image: { src: '', alt: '', caption: '' },
      video: { src: '', poster: '' },
      code: { lang: '', code: '' },
      callout: { variant: 'info', title: '', md: '' },
      list: { ordered: false, items: [''] },
      separator: {},
    }[type] || {};
    return { id: uid(), type, data: d };
  }

  function el(tag, attrs, children) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') n.className = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(c => {
      if (c == null) return;
      if (typeof c === 'string') n.appendChild(document.createTextNode(c));
      else n.appendChild(c);
    });
    return n;
  }

  function mount(root, opts) {
    opts = opts || {};
    const state = { sections: JSON.parse(JSON.stringify(opts.initial || [])) };
    if (!state.sections.length) state.sections.push({ id: uid(), title: 'New Section', blocks: [] });

    root.classList.add('be-root');
    root.innerHTML = '';

    const sectionsEl = el('div', { class: 'be-sections' });
    root.appendChild(sectionsEl);

    const addSectionBtn = el('button', {
      type: 'button', class: 'btn be-add-section',
      onclick: () => {
        state.sections.push({ id: uid(), title: 'New Section', blocks: [] });
        render();
      }
    }, ['+ Add section']);
    root.appendChild(addSectionBtn);

    function render() {
      sectionsEl.innerHTML = '';
      state.sections.forEach((sec, idx) => sectionsEl.appendChild(renderSection(sec, idx)));
      // Sortable on sections
      Sortable.create(sectionsEl, {
        handle: '.be-section-drag',
        animation: 150,
        onEnd: (e) => {
          const [moved] = state.sections.splice(e.oldIndex, 1);
          state.sections.splice(e.newIndex, 0, moved);
        },
      });
    }

    function renderSection(sec, idx) {
      const wrap = el('div', { class: 'be-section', 'data-id': sec.id });
      const head = el('div', { class: 'be-section-head' }, [
        el('span', { class: 'be-section-drag', title: 'Drag to reorder' }, ['⋮⋮']),
        el('input', {
          type: 'text', class: 'be-section-title', value: sec.title || '',
          placeholder: 'Section title',
          oninput: (e) => { sec.title = e.target.value; },
        }),
        el('button', {
          type: 'button', class: 'icon-btn be-remove', title: 'Delete section',
          onclick: () => {
            if (!confirm('Delete this section and its blocks?')) return;
            state.sections.splice(idx, 1); render();
          }
        }, ['✕']),
      ]);
      wrap.appendChild(head);

      const blocksEl = el('div', { class: 'be-blocks' });
      sec.blocks.forEach((b, bi) => blocksEl.appendChild(renderBlock(sec, b, bi)));
      wrap.appendChild(blocksEl);

      Sortable.create(blocksEl, {
        group: 'be-blocks',
        handle: '.be-block-drag',
        animation: 150,
        onAdd: (e) => moveBlockBetween(e),
        onEnd: (e) => {
          if (e.from === e.to) {
            const [moved] = sec.blocks.splice(e.oldIndex, 1);
            sec.blocks.splice(e.newIndex, 0, moved);
          }
        },
      });

      const addBar = el('div', { class: 'be-add-block-bar' });
      BLOCK_TYPES.forEach(bt => {
        addBar.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm be-add-block', title: `Add ${bt.label}`,
          onclick: () => { sec.blocks.push(blankBlock(bt.type)); render(); },
        }, [bt.icon + ' ' + bt.label]));
      });
      wrap.appendChild(addBar);
      return wrap;
    }

    function moveBlockBetween(e) {
      // When a block is dragged from one section to another, move it in state
      const fromSecId = e.from.closest('.be-section').dataset.id;
      const toSecId = e.to.closest('.be-section').dataset.id;
      const from = state.sections.find(s => s.id === fromSecId);
      const to = state.sections.find(s => s.id === toSecId);
      if (!from || !to) return;
      const [moved] = from.blocks.splice(e.oldIndex, 1);
      to.blocks.splice(e.newIndex, 0, moved);
    }

    function renderBlock(sec, b, bi) {
      const wrap = el('div', { class: 'be-block be-block-' + b.type, 'data-id': b.id });
      const head = el('div', { class: 'be-block-head' }, [
        el('span', { class: 'be-block-drag', title: 'Drag to reorder' }, ['⋮⋮']),
        el('span', { class: 'be-block-type' }, [b.type]),
        el('button', {
          type: 'button', class: 'icon-btn be-remove', title: 'Remove block',
          onclick: () => { sec.blocks.splice(bi, 1); render(); }
        }, ['✕']),
      ]);
      wrap.appendChild(head);
      wrap.appendChild(renderBlockBody(b));
      return wrap;
    }

    function ta(value, oninput, opts2) {
      return el('textarea', Object.assign({
        rows: (opts2 && opts2.rows) || 4,
        placeholder: (opts2 && opts2.placeholder) || '',
        oninput: (e) => oninput(e.target.value),
      }, opts2 && opts2.attrs || {}), [value || '']);
    }

    function renderBlockBody(b) {
      const d = b.data;
      if (b.type === 'paragraph') {
        return el('div', { class: 'be-body' }, [
          ta(d.md, v => d.md = v, { rows: 5, placeholder: 'Markdown text…' }),
        ]);
      }
      if (b.type === 'heading') {
        const lvlSel = el('select', {
          onchange: e => d.level = parseInt(e.target.value, 10)
        }, [2,3,4,5].map(n => {
          const o = el('option', { value: n }, ['H'+n]);
          if ((d.level||3) === n) o.selected = true;
          return o;
        }));
        return el('div', { class: 'be-body be-row' }, [
          lvlSel,
          el('input', {
            type: 'text', placeholder: 'Heading text',
            value: d.text || '', oninput: e => d.text = e.target.value
          }),
        ]);
      }
      if (b.type === 'image') {
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Image URL or /uploads/…',
            el('input', { type: 'text', value: d.src || '', oninput: e => d.src = e.target.value })]),
          el('label', {}, ['Alt text',
            el('input', { type: 'text', value: d.alt || '', oninput: e => d.alt = e.target.value })]),
          el('label', {}, ['Caption',
            el('input', { type: 'text', value: d.caption || '', oninput: e => d.caption = e.target.value })]),
          d.src ? el('img', { src: d.src, class: 'be-preview' }) : null,
        ]);
      }
      if (b.type === 'video') {
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Video URL or /uploads/…',
            el('input', { type: 'text', value: d.src || '', oninput: e => d.src = e.target.value })]),
          el('label', {}, ['Poster (optional)',
            el('input', { type: 'text', value: d.poster || '', oninput: e => d.poster = e.target.value })]),
        ]);
      }
      if (b.type === 'code') {
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Language',
            el('input', { type: 'text', value: d.lang || '', placeholder: 'e.g. python', oninput: e => d.lang = e.target.value })]),
          ta(d.code, v => d.code = v, { rows: 8, placeholder: 'Code…', attrs: { style: 'font-family: ui-monospace, Menlo, monospace;' } }),
        ]);
      }
      if (b.type === 'callout') {
        const vSel = el('select', { onchange: e => d.variant = e.target.value },
          ['info','warn','danger','success'].map(v => {
            const o = el('option', { value: v }, [v]);
            if ((d.variant||'info') === v) o.selected = true;
            return o;
          }));
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Variant', vSel]),
          el('label', {}, ['Title',
            el('input', { type: 'text', value: d.title || '', oninput: e => d.title = e.target.value })]),
          ta(d.md, v => d.md = v, { rows: 4, placeholder: 'Markdown body…' }),
        ]);
      }
      if (b.type === 'list') {
        const body = el('div', { class: 'be-body' });
        const orderedChk = el('label', { class: 'be-row' }, [
          el('input', {
            type: 'checkbox', checked: d.ordered ? 'checked' : null,
            onchange: e => { d.ordered = e.target.checked; }
          }),
          el('span', {}, ['Ordered (numbered)'])
        ]);
        body.appendChild(orderedChk);
        const items = el('div', { class: 'be-list-items' });
        (d.items || []).forEach((it, ii) => {
          const row = el('div', { class: 'be-row' }, [
            el('input', {
              type: 'text', value: it, oninput: e => d.items[ii] = e.target.value,
              placeholder: 'List item (markdown)'
            }),
            el('button', { type: 'button', class: 'icon-btn', title: 'Remove',
              onclick: () => { d.items.splice(ii,1); render(); } }, ['✕']),
          ]);
          items.appendChild(row);
        });
        body.appendChild(items);
        body.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => { d.items = d.items || []; d.items.push(''); render(); }
        }, ['+ Add item']));
        return body;
      }
      if (b.type === 'separator') {
        return el('div', { class: 'be-body muted small' }, ['Horizontal divider (no options)']);
      }
      return el('div', { class: 'be-body' }, ['Unknown block type: ' + b.type]);
    }

    function serialize() {
      return JSON.stringify(state.sections);
    }

    render();
    return { serialize, getState: () => state.sections };
  }

  window.BlockEditor = { mount };
})();
