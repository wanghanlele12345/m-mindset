document.addEventListener('DOMContentLoaded', () => {
    const state = {
        currentRootCategory: '哲学',
        data: [],
        filteredData: [],
        sortCol: 'rating',
        sortDesc: true,
        searchQuery: '',
        statusFilter: 'all',
        selectedCategories: new Set(),
        selectedTags: {},
        minRating: null,
        maxRating: null
    };

    const el = {
        tableBody: document.getElementById('table-body'),
        headers: document.querySelectorAll('.sortable'),
        shownCount: document.getElementById('shown-count'),
        totalCount: document.getElementById('total-count'),
        searchInput: document.getElementById('search-input'),
        emptyState: document.getElementById('empty-state'),
        modal: document.getElementById('book-modal'),
        modalContent: document.getElementById('modal-body'),
        closeBtn: document.querySelector('.close-btn'),
        categoryList: document.getElementById('category-list'),
        clearCategories: document.getElementById('clear-categories'),
        clearAllFiltersBtn: document.getElementById('clear-all-filters'),
        navItems: document.querySelectorAll('.sidebar-nav-item'),
        themeLightBtn: document.getElementById('theme-light-btn'),
        themeDarkBtn: document.getElementById('theme-dark-btn'),
    };

    // ============ Theme Toggles ============
    function setTheme(theme) {
        if (theme === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
            if (el.themeLightBtn) el.themeLightBtn.style.opacity = '1';
            if (el.themeDarkBtn) el.themeDarkBtn.style.opacity = '0.5';
            localStorage.setItem('app-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
            if (el.themeLightBtn) el.themeLightBtn.style.opacity = '0.5';
            if (el.themeDarkBtn) el.themeDarkBtn.style.opacity = '1';
            localStorage.setItem('app-theme', 'dark');
        }
    }

    const savedTheme = localStorage.getItem('app-theme') || 'dark';
    setTheme(savedTheme);

    if (el.themeLightBtn && el.themeDarkBtn) {
        el.themeLightBtn.addEventListener('click', () => setTheme('light'));
        el.themeDarkBtn.addEventListener('click', () => setTheme('dark'));
    }

    // ============ Init ============
    async function init() {
        const btn = document.getElementById('view-other-btn');
        if (btn) btn.href = `/${encodeURIComponent(state.currentRootCategory)}/others`;

        await reloadData();
        // Auto-refresh
        setInterval(fetchUpdate, 15000);
    }

    async function reloadData() {
        el.tableBody.innerHTML = `<tr><td colspan="9"><div class="skeleton"></div></td></tr>`;
        try {
            const booksRes = await fetch(`/api/books?root_category=${encodeURIComponent(state.currentRootCategory)}`);
            const booksResult = await booksRes.json();
            if (booksResult.error) {
                el.tableBody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--accent);">Error: ${booksResult.error}</td></tr>`;
                return;
            }
            state.data = booksResult.data || [];

            state.data.forEach(b => {
                const r = parseFloat(b.rating) || 0;
                const c = typeof b.rating_count === 'string' ? parseInt(b.rating_count.replace(/[^0-9]/g, '')) || 0 : (b.rating_count || 0);
                b.total_score = r * c;
            });

            // Reset filters on reload
            state.selectedCategories.clear();
            for (let k in state.selectedTags) state.selectedTags[k].clear();
            el.searchInput.value = '';
            state.searchQuery = '';

            applyFiltersAndSort();

            // Load categories for sidebar (non-blocking)
            loadCategories();
        } catch (err) {
            console.error(err);
            el.tableBody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--accent);">连接失败</td></tr>`;
        }
    }

    async function loadCategories() {
        try {
            const res = await fetch(`/api/categories?root_category=${encodeURIComponent(state.currentRootCategory)}`);
            const result = await res.json();
            if (result.error) return;
            renderCategoryCheckboxes(result.categories || []);
            renderTagCheckboxes(result.tag_dimensions || {});
        } catch (e) {
            console.warn('Failed to load categories', e);
        }
    }

    // ============ Sidebar Rendering ============
    function renderCategoryCheckboxes(categories) {
        if (!categories.length) {
            el.categoryList.innerHTML = '<span class="sidebar-empty">暂无分类数据</span>';
            return;
        }

        // Sort categories numerically (e.g. 1.2, 2.1, 10.1)
        categories.sort((a, b) => {
            const codeA = a.category_code || '';
            const codeB = b.category_code || '';
            return codeA.localeCompare(codeB, undefined, { numeric: true, sensitivity: 'base' });
        });

        if (state.currentRootCategory === '哲学' || state.currentRootCategory === '心理学') {
            const PHILOSOPHY_MAJOR_CATEGORIES = {
                "1": "01. 哲学总论与工具书",
                "2": "02. 哲学史与西方哲学流派",
                "3": "03. 中国与东方哲学",
                "4": "04. 形而上学与心灵哲学",
                "5": "05. 认识论与科学哲学",
                "6": "06. 逻辑学与语言哲学",
                "7": "07. 伦理学与价值论",
                "8": "08. 政治、社会与法哲学",
                "9": "09. 美学与艺术哲学",
                "10": "10. 跨学科哲学"
            };

            const PSYCHOLOGY_MAJOR_CATEGORIES = {
                "1": "01. 心理学总论与史传",
                "2": "02. 生理与认知心理学",
                "3": "03. 发展与教育心理学",
                "4": "04. 人格与社会心理学",
                "5": "05. 临床与变态心理学",
                "6": "06. 心理咨询与治疗",
                "7": "07. 积极心理学与情绪科学",
                "8": "08. 应用心理学",
                "9": "09. 泛心理学与个人成长",
                "10": "10. 跨学科心理学"
            };

            const activeCategories = state.currentRootCategory === '哲学' ? PHILOSOPHY_MAJOR_CATEGORIES : PSYCHOLOGY_MAJOR_CATEGORIES;

            const groupedCategories = {};
            const otherCategories = [];

            categories.forEach(c => {
                const major = c.category_code ? c.category_code.split('.')[0] : null;
                if (major && activeCategories[major] && c.category_code.includes('.')) {
                    if (!groupedCategories[major]) {
                        groupedCategories[major] = [];
                    }
                    groupedCategories[major].push(c);
                } else {
                    otherCategories.push(c);
                }
            });

            let html = '';

            // Render grouped
            Object.keys(activeCategories).sort((a, b) => parseInt(a) - parseInt(b)).forEach(majorKey => {
                if (groupedCategories[majorKey] && groupedCategories[majorKey].length > 0) {
                    html += `<div class="major-category-title">${esc(activeCategories[majorKey])}</div>`;
                    groupedCategories[majorKey].forEach(c => {
                        const shortName = (c.category_name || '').split('（')[0].split('(')[0].trim();
                        html += `<label class="checkbox-item" style="padding-left: 12px;">
                            <input type="checkbox" data-code="${esc(c.category_code)}">
                            <span class="cb-code">${esc(c.category_code)}</span>
                            <span class="cb-label">${esc(shortName)}</span>
                            <span class="cb-count">${c.count}</span>
                        </label>`;
                    });
                }
            });

            // Render others
            if (otherCategories.length > 0) {
                html += `<div class="major-category-title">其他</div>`;
                otherCategories.forEach(c => {
                    const shortName = (c.category_name || '').split('（')[0].split('(')[0].trim();
                    html += `<label class="checkbox-item" style="padding-left: 12px;">
                        <input type="checkbox" data-code="${esc(c.category_code)}">
                        <span class="cb-code">${esc(c.category_code)}</span>
                        <span class="cb-label">${esc(shortName)}</span>
                        <span class="cb-count">${c.count}</span>
                    </label>`;
                });
            }

            el.categoryList.innerHTML = html;
        } else {
            el.categoryList.innerHTML = categories.map(c => {
                const shortName = (c.category_name || '').split('（')[0].split('(')[0].trim();
                return `<label class="checkbox-item">
                    <input type="checkbox" data-code="${esc(c.category_code)}">
                    <span class="cb-code">${esc(c.category_code)}</span>
                    <span class="cb-label">${esc(shortName)}</span>
                    <span class="cb-count">${c.count}</span>
                </label>`;
            }).join('');
        }

        el.categoryList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', () => {
                if (cb.checked) state.selectedCategories.add(cb.dataset.code);
                else state.selectedCategories.delete(cb.dataset.code);
                applyFiltersAndSort();
            });
        });
    }

    function renderTagCheckboxes(tagDims) {
        const dims = ['流派', '时代', '性质', '主题', '人物'];
        for (const dim of dims) {
            const container = document.getElementById(`tag-list-${dim}`);
            const section = document.getElementById(`tag-section-${dim}`);
            const tags = tagDims[dim];
            if (!tags || !tags.length) {
                if (section) section.style.display = 'none';
                continue;
            } else {
                if (section) section.style.display = 'block';
            }
            state.selectedTags[dim] = new Set();
            const shown = tags.slice(0, 20);
            container.innerHTML = shown.map(t =>
                `<label class="checkbox-item">
                    <input type="checkbox" data-dim="${esc(dim)}" data-value="${esc(t.value)}">
                    <span class="cb-label">${esc(t.value)}</span>
                    <span class="cb-count">${t.count}</span>
                </label>`
            ).join('');

            container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', () => {
                    if (cb.checked) state.selectedTags[dim].add(cb.dataset.value);
                    else state.selectedTags[dim].delete(cb.dataset.value);
                    applyFiltersAndSort();
                });
            });
        }
    }

    // ============ Collapsible Sidebar ============
    document.querySelectorAll('.collapsible-header').forEach(header => {
        header.addEventListener('click', () => {
            const section = header.closest('.collapsible-section');
            if (section) section.classList.toggle('collapsed');
        });
    });

    // ============ Events ============
    el.navItems.forEach(item => {
        item.addEventListener('click', async () => {
            if (item.classList.contains('active')) return;

            el.navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            state.currentRootCategory = item.dataset.root;

            const btn = document.getElementById('view-other-btn');
            if (btn) btn.href = `/${encodeURIComponent(state.currentRootCategory)}/others`;

            await reloadData();
        });
    });

    el.clearAllFiltersBtn.addEventListener('click', () => {
        // Clear search
        state.searchQuery = '';
        el.searchInput.value = '';

        // Clear status
        state.statusFilter = 'all';
        document.querySelector('input[name="status-filter"][value="all"]').checked = true;

        // Clear rating
        state.minRating = null;
        state.maxRating = null;
        document.getElementById('min-rating').value = '';
        document.getElementById('max-rating').value = '';

        // Clear categories
        state.selectedCategories.clear();
        el.categoryList.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);

        // Clear tags
        for (let dim in state.selectedTags) {
            state.selectedTags[dim].clear();
            const container = document.getElementById(`tag-list-${dim}`);
            if (container) {
                container.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            }
        }

        applyFiltersAndSort();
    });

    el.searchInput.addEventListener('input', e => {
        state.searchQuery = e.target.value.toLowerCase().trim();
        applyFiltersAndSort();
    });

    document.querySelectorAll('input[name="status-filter"]').forEach(radio => {
        radio.addEventListener('change', () => {
            state.statusFilter = radio.value;
            applyFiltersAndSort();
        });
    });

    document.getElementById('min-rating').addEventListener('input', e => {
        const val = parseFloat(e.target.value);
        state.minRating = isNaN(val) ? null : val;
        applyFiltersAndSort();
    });

    document.getElementById('max-rating').addEventListener('input', e => {
        const val = parseFloat(e.target.value);
        state.maxRating = isNaN(val) ? null : val;
        applyFiltersAndSort();
    });

    el.clearCategories.addEventListener('click', (e) => {
        e.stopPropagation();
        state.selectedCategories.clear();
        el.categoryList.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
        applyFiltersAndSort();
    });

    document.querySelectorAll('.clear-btn[data-dim]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const dim = btn.dataset.dim;
            if (state.selectedTags[dim]) state.selectedTags[dim].clear();
            const container = document.getElementById(`tag-list-${dim}`);
            if (container) container.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            applyFiltersAndSort();
        });
    });

    el.headers.forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (state.sortCol === col) {
                state.sortDesc = !state.sortDesc;
            } else {
                state.sortCol = col;
                state.sortDesc = ['rating', 'rating_count', 'id', 'total_score'].includes(col);
            }
            updateHeadersUI();
            applyFiltersAndSort();
        });
    });

    el.closeBtn.addEventListener('click', closeModal);
    window.addEventListener('click', e => { if (e.target === el.modal) closeModal(); });
    window.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

    // ============ Core Filter & Sort ============
    function applyFiltersAndSort() {
        state.filteredData = state.data.filter(book => {
            // Search
            if (state.searchQuery) {
                const q = state.searchQuery;
                const match = (book.title && book.title.toLowerCase().includes(q)) ||
                    (book.author && book.author.toLowerCase().includes(q)) ||
                    (book.publisher && book.publisher.toLowerCase().includes(q)) ||
                    (book.category_name && book.category_name.toLowerCase().includes(q));
                if (!match) return false;
            }

            // Status
            if (state.statusFilter === 'classified' && !book.category_code) return false;
            if (state.statusFilter === 'unclassified' && book.category_code) return false;

            // Rating
            const rat = parseFloat(book.rating);
            const hasRat = !isNaN(rat);
            if (state.minRating !== null) {
                if (!hasRat || rat < state.minRating) return false;
            }
            if (state.maxRating !== null) {
                if (!hasRat || rat > state.maxRating) return false;
            }

            // Category (OR within selected categories)
            if (state.selectedCategories.size > 0) {
                if (!book.category_code || !state.selectedCategories.has(book.category_code)) return false;
            }

            // Tags (each dimension is OR within, AND across dimensions)
            for (const [dim, vals] of Object.entries(state.selectedTags)) {
                if (vals.size === 0) continue;
                const bookTags = (book.tags && book.tags[dim]) || [];
                const hasMatch = bookTags.some(t => vals.has(t));
                if (!hasMatch) return false;
            }

            return true;
        });

        // Sort
        state.filteredData.sort((a, b) => {
            let va = a[state.sortCol], vb = b[state.sortCol];
            if (va == null || va === '') va = state.sortDesc ? -Infinity : Infinity;
            if (vb == null || vb === '') vb = state.sortDesc ? -Infinity : Infinity;

            if (['rating', 'price', 'id', 'total_score'].includes(state.sortCol)) {
                if (state.sortCol === 'price' && typeof va === 'string') va = parseFloat(va.replace(/[^0-9.]/g, '')) || 0;
                if (state.sortCol === 'price' && typeof vb === 'string') vb = parseFloat(vb.replace(/[^0-9.]/g, '')) || 0;
                va = parseFloat(va) || 0;
                vb = parseFloat(vb) || 0;
            }
            if (state.sortCol === 'rating_count') {
                va = typeof va === 'string' ? parseInt(va.replace(/[^0-9]/g, '')) || 0 : 0;
                vb = typeof vb === 'string' ? parseInt(vb.replace(/[^0-9]/g, '')) || 0 : 0;
            }

            if (va < vb) return state.sortDesc ? 1 : -1;
            if (va > vb) return state.sortDesc ? -1 : 1;
            return 0;
        });

        renderTable();
        updateDynamicCounts();
    }

    function updateDynamicCounts() {
        const dims = ['流派', '时代', '性质', '主题', '人物'];
        const tagCounts = {};
        dims.forEach(d => tagCounts[d] = {});

        state.filteredData.forEach(book => {
            if (!book.tags) return;
            dims.forEach(dim => {
                if (book.tags[dim]) {
                    book.tags[dim].forEach(val => {
                        tagCounts[dim][val] = (tagCounts[dim][val] || 0) + 1;
                    });
                }
            });
        });

        dims.forEach(dim => {
            const container = document.getElementById(`tag-list-${dim}`);
            if (!container) return;
            container.querySelectorAll('label.checkbox-item').forEach(label => {
                const cb = label.querySelector('input[type="checkbox"]');
                const countSpan = label.querySelector('.cb-count');
                const val = cb.dataset.value;
                const count = tagCounts[dim][val] || 0;
                countSpan.textContent = count;

                if (count === 0 && !cb.checked) {
                    label.style.opacity = '0.4';
                } else {
                    label.style.opacity = '1';
                }
            });
        });
    }

    // ============ Helpers ============
    function getCoverUrl(book) {
        const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
        const remoteUrl = book.cover_remote_url;
        const localPath = book.cover_screenshot ? '/covers/' + book.cover_screenshot.split('/').pop() : '';

        // If in cloud (Vercel), always prefer remote URL if it exists
        if (!isLocal && remoteUrl) return remoteUrl;
        
        // If local, prefer local path but fallback to remote if needed
        return localPath || remoteUrl || '';
    }

    // ============ Render Table ============
    function renderTable() {
        el.shownCount.textContent = state.filteredData.length;
        el.totalCount.textContent = state.data.length;

        if (state.filteredData.length === 0) {
            el.tableBody.innerHTML = '';
            el.emptyState.style.display = 'flex';
            return;
        }
        el.emptyState.style.display = 'none';

        el.tableBody.innerHTML = state.filteredData.map(book => {
            const coverUrl = getCoverUrl(book);
            const fallbackUrl = book.cover_remote_url; // Remote as ultimate fallback
            const coverImg = coverUrl ? 
                `<img src="${coverUrl}" class="table-cover" loading="lazy" onerror="if(this.src!=='${fallbackUrl}'){this.src='${fallbackUrl}';}else{this.style.display='none';}" alt="">` : 
                '<div class="table-cover-placeholder"></div>';

            let catHTML = '';
            let tagsHTML = '';
            if (book.category_code) {
                const shortName = (book.category_name || '').split('（')[0].split('(')[0].trim();
                const cls = book.confidence === 'high' ? 'conf-high' : book.confidence === 'medium' ? 'conf-med' : 'conf-low';
                catHTML = `<span class="cat-badge ${cls}">${esc(book.category_code)} ${esc(shortName)}</span>`;
                // Show key tags
                if (book.tags) {
                    const pills = [];
                    for (const dim of ['流派', '时代']) {
                        const vals = book.tags[dim];
                        if (vals) vals.slice(0, 1).forEach(v => pills.push(`<span class="tag-pill">${esc(v)}</span>`));
                    }
                    tagsHTML = pills.join('');
                }
            }

            return `<tr data-id="${book.id}">
                <td class="td-id">#${book.id}</td>
                <td class="td-cover">${coverImg}</td>
                <td class="td-title">${esc(book.title || '-')}</td>
                <td class="td-category">${catHTML}</td>
                <td class="td-tags">${tagsHTML}</td>
                <td class="td-author">${esc(book.author || '-')}</td>
                <td class="td-rating">${esc(book.rating || '-')}</td>
                <td>${esc(book.rating_count || '-')}</td>
                <td class="td-total-score">${book.total_score ? book.total_score.toFixed(1) : '-'}</td>
            </tr>`;
        }).join('');

        el.tableBody.querySelectorAll('tr').forEach(row => {
            row.addEventListener('click', () => {
                const book = state.filteredData.find(b => b.id === parseInt(row.dataset.id));
                if (book) openModal(book);
            });
        });
    }

    function updateHeadersUI() {
        el.headers.forEach(th => {
            th.classList.remove('asc', 'desc');
            const icon = th.querySelector('.sort-icon');
            if (th.dataset.sort === state.sortCol) {
                th.classList.add(state.sortDesc ? 'desc' : 'asc');
                icon.textContent = '▼';
            } else {
                icon.textContent = '';
            }
        });
    }

    // ============ Modal ============
    function openModal(book) {
        const coverUrl = getCoverUrl(book);
        const fallbackUrl = book.cover_remote_url;
        let content = `
            <div class="modal-header">
                <div class="modal-header-content">
                    ${coverUrl ? `<img src="${coverUrl}" class="modal-cover" onerror="if(this.src!=='${fallbackUrl}'){this.src='${fallbackUrl}';}" alt="封面">` : ''}
                    <div>
                        <h2 class="modal-title">${esc(book.title)}</h2>
                        ${book.subtitle ? `<div class="modal-subtitle">${esc(book.subtitle)}</div>` : ''}
                    </div>
                </div>
            </div>`;

        if (book.category_code) {
            content += `<div class="modal-classification">
                <span class="modal-cat-label">${esc(book.category_code)} ${esc(book.category_name || '')}</span>
                <span class="modal-conf conf-${book.confidence || 'low'}">${book.confidence || '-'}</span>
            </div>`;
            if (book.tags && Object.keys(book.tags).length) {
                content += '<div class="modal-tags">';
                for (const [dim, vals] of Object.entries(book.tags)) {
                    content += `<div class="modal-tag-row">
                        <span class="modal-tag-dim">${esc(dim)}</span>
                        ${vals.map(v => `<span class="modal-tag-val">${esc(v)}</span>`).join('')}
                    </div>`;
                }
                content += '</div>';
            }
        }

        content += `<div class="modal-meta">
            <div class="meta-item"><div class="meta-label">作者</div><div class="meta-value">${esc(book.author || '-')}</div></div>
            ${book.translator ? `<div class="meta-item"><div class="meta-label">译者</div><div class="meta-value">${esc(book.translator)}</div></div>` : ''}
            <div class="meta-item"><div class="meta-label">出版社</div><div class="meta-value">${esc(book.publisher || '-')}</div></div>
            <div class="meta-item"><div class="meta-label">出版日期</div><div class="meta-value">${esc(book.pub_date || '-')}</div></div>
            <div class="meta-item"><div class="meta-label">定价</div><div class="meta-value">${esc(book.price || '-')}</div></div>
            ${book.pages ? `<div class="meta-item"><div class="meta-label">页数</div><div class="meta-value">${esc(book.pages)}</div></div>` : ''}
            <div class="meta-item"><div class="meta-label">评分</div><div class="meta-value rating">${esc(book.rating || '-')} <span style="font-size:0.75rem;color:var(--text-muted);font-weight:normal">(${esc(book.rating_count || '0')})</span></div></div>
        </div>`;

        if (book.description) content += `<div class="meta-label" style="margin-bottom:8px">简介</div><div class="modal-desc">${fmtDesc(book.description)}</div>`;
        if (book.catalog) content += `<div class="meta-label" style="margin-top:20px;margin-bottom:8px">目录</div><div class="modal-catalog">${esc(book.catalog)}</div>`;
        if (book.excerpt) content += `<div class="meta-label" style="margin-top:20px;margin-bottom:8px">摘录</div><div class="modal-excerpt">${fmtDesc(book.excerpt)}</div>`;

        if (book.url) {
            const link = book.url.startsWith('android_app://') ?
                `<span style="color:var(--text-muted);font-size:0.85rem">App: ${book.url}</span>` :
                `<a href="${book.url}" target="_blank" style="color:var(--primary);text-decoration:none">在豆瓣查看 →</a>`;
            content += `<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border-color)">${link}</div>`;
        }

        // Add WeRead Automation Button
        content += `<button class="btn-open-weread" data-id="${book.id}">
                        📖 在微信读书中查看
                    </button>`;

        // Add Delete Button
        content += `<button class="btn-delete-book" data-id="${book.id}">
                        🗑️ 删除该书目
                    </button>`;

        el.modalContent.innerHTML = content;
        el.modal.style.display = 'flex';
        setTimeout(() => { el.modal.classList.add('show'); document.body.style.overflow = 'hidden'; }, 10);

        // Attach Trigger Event for WeRead
        const openBtn = el.modalContent.querySelector('.btn-open-weread');
        if (openBtn) {
            openBtn.addEventListener('click', async () => {
                const originalText = openBtn.innerHTML;
                openBtn.innerHTML = '⏳ 正在调起模拟器并搜索，请稍候...';
                openBtn.disabled = true;

                try {
                    const response = await fetch('/api/open_weread', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            title: book.title,
                            author: book.author || ''
                        })
                    });

                    const result = await response.json();

                    if (result.success) {
                        openBtn.innerHTML = '✅ 已在模拟器中打开';
                        setTimeout(() => closeModal(), 1000);
                    } else {
                        throw new Error(result.error || 'Unknown automation error');
                    }
                } catch (err) {
                    console.error('WeRead automation failed:', err);
                    alert('自动化跳转失败: ' + err.message);
                    openBtn.innerHTML = originalText;
                    openBtn.disabled = false;
                }
            });
        }

        // Attach Delete Event
        const delBtn = el.modalContent.querySelector('.btn-delete-book');
        if (delBtn) {
            delBtn.addEventListener('click', async () => {
                if (!window.confirm('您确定要从数据库中彻底删除这本书吗？\n此操作不可恢复，将连同它的分类与标签一起删除！')) {
                    return;
                }

                const originalText = delBtn.innerHTML;
                delBtn.innerHTML = '⏳ 删除中...';
                delBtn.disabled = true;

                try {
                    const response = await fetch('/api/delete_book', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ book_id: book.id })
                    });

                    const result = await response.json();

                    if (result.success) {
                        // Remove from state
                        state.data = state.data.filter(b => b.id !== book.id);
                        applyFiltersAndSort();
                        closeModal();
                    } else {
                        throw new Error(result.error || 'Unknown error');
                    }
                } catch (err) {
                    console.error('Delete failed:', err);
                    alert('删除失败: ' + err.message);
                    delBtn.innerHTML = originalText;
                    delBtn.disabled = false;
                }
            });
        }
    }

    function closeModal() {
        el.modal.classList.remove('show');
        document.body.style.overflow = '';
        setTimeout(() => { el.modal.style.display = 'none'; }, 300);
    }

    async function fetchUpdate() {
        try {
            const res = await fetch(`/api/books?root_category=${encodeURIComponent(state.currentRootCategory)}`);
            const result = await res.json();
            if (!result.error && result.data) {
                // Calculate total_score first so it matches the structure
                result.data.forEach(b => {
                    const r = parseFloat(b.rating) || 0;
                    const c = typeof b.rating_count === 'string' ? parseInt(b.rating_count.replace(/[^0-9]/g, '')) || 0 : (b.rating_count || 0);
                    b.total_score = r * c;
                });

                // Only update if there are actual changes to prevent UI flashing
                if (JSON.stringify(state.data) !== JSON.stringify(result.data)) {
                    state.data = result.data;
                    applyFiltersAndSort();
                }
            }
        } catch (e) { /* ignore */ }
    }

    // ============ Helpers ============
    function esc(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function fmtDesc(text) {
        if (!text) return '';
        const escaped = esc(text);
        const sentences = escaped.split(/(?<=[\u3002\uff01\uff1f])/g).filter(s => s.trim());
        if (sentences.length <= 3) return `<p>${escaped}</p>`;
        const paras = [];
        for (let i = 0; i < sentences.length; i += 3) paras.push(sentences.slice(i, i + 3).join(''));
        return paras.map(p => `<p>${p.trim()}</p>`).join('');
    }

    init();
    updateHeadersUI();
});
