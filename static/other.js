document.addEventListener('DOMContentLoaded', () => {
    // State
    let state = {
        books: [],
        filteredBooks: [],
        filters: {
            onlyCategory: true,
            searchQuery: ''
        }
    };

    // DOM Elements
    const elements = {
        grid: document.getElementById('books-grid'),
        loading: document.getElementById('loading'),
        emptyState: document.getElementById('empty-state'),
        shownCount: document.getElementById('shown-count'),
        filterCategory: document.getElementById('filter-category'),
        searchInput: document.getElementById('search-input'),
        themeLightBtn: document.getElementById('theme-light-btn'),
        themeDarkBtn: document.getElementById('theme-dark-btn'),
    };

    // Helpers
    function esc(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    // Theme Management
    function initTheme() {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        setTheme(savedTheme);

        elements.themeLightBtn.addEventListener('click', () => setTheme('light'));
        elements.themeDarkBtn.addEventListener('click', () => setTheme('dark'));
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);

        if (theme === 'light') {
            elements.themeLightBtn.style.opacity = '1';
            elements.themeDarkBtn.style.opacity = '0.5';
        } else {
            elements.themeLightBtn.style.opacity = '0.5';
            elements.themeDarkBtn.style.opacity = '1';
        }
    }

    // Data Fetching
    let rootCategory = '';
    const pathParts = window.location.pathname.split('/');
    if (pathParts.length >= 3 && pathParts[pathParts.length - 1] === 'others') {
        rootCategory = decodeURIComponent(pathParts[pathParts.length - 2]);
    }

    if (rootCategory) {
        document.title = `Millenniums Midset - ${rootCategory} 其他`;
        const headerTitle = document.getElementById('header-title');
        if (headerTitle) {
            headerTitle.textContent = `Millenniums Midset - ${rootCategory} 其他`;
        }
        const filterLabel = document.getElementById('filter-label');
        if (filterLabel) {
            filterLabel.textContent = `只看被认为是“${rootCategory}”的书籍`;
        }
    }

    async function fetchBooks() {
        try {
            elements.loading.style.display = 'block';
            elements.grid.style.display = 'none';

            const url = rootCategory ? `/api/other_books?root_category=${encodeURIComponent(rootCategory)}` : '/api/other_books';
            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Error fetching books:', data.error);
                elements.loading.textContent = '加载失败: ' + data.error;
                return;
            }

            state.books = data.data;
            applyFilters();

            elements.loading.style.display = 'none';
            elements.grid.style.display = 'grid';
        } catch (error) {
            console.error('Fetch error:', error);
            elements.loading.textContent = '网络请求失败';
        }
    }

    // Filtering
    function applyFilters() {
        state.filteredBooks = state.books.filter(book => {
            // Check category filter
            let passesCategory = true;
            if (state.filters.onlyCategory) {
                // Check multiple ways category flag might be represented in the DB
                const isPhil = book.is_philosophy;
                const belongs = book.belongs_to_category;
                passesCategory = (isPhil === 1 || isPhil === '1' || isPhil === 'true' || isPhil === 'True' ||
                    belongs === 1 || belongs === '1' || belongs === 'true' || belongs === 'True');
            }

            if (!passesCategory) return false;

            // Check search query
            if (state.filters.searchQuery) {
                const query = state.filters.searchQuery.toLowerCase();
                const textToSearch = `${book.title} ${book.author} ${book.suggested_category} ${book.reason}`.toLowerCase();
                if (!textToSearch.includes(query)) return false;
            }

            return true;
        });

        renderGrid();
    }

    // Rendering
    function renderGrid() {
        elements.shownCount.textContent = state.filteredBooks.length;

        if (state.filteredBooks.length === 0) {
            elements.grid.style.display = 'none';
            elements.emptyState.style.display = 'flex';
            return;
        }

        elements.grid.style.display = 'grid';
        elements.emptyState.style.display = 'none';

        elements.grid.innerHTML = state.filteredBooks.map(book => {
            const isPhilVal = book.is_philosophy;
            const belongsVal = book.belongs_to_category;
            const isCategoryMatched = (isPhilVal === 1 || isPhilVal === '1' || isPhilVal === 'true' || isPhilVal === 'True' ||
                belongsVal === 1 || belongsVal === '1' || belongsVal === 'true' || belongsVal === 'True');

            // Format fallback cover
            const coverFilename = book.cover_screenshot ? book.cover_screenshot.split('/').pop() : '';
            const coverHtml = coverFilename
                ? `<img class="card-cover" src="/covers/${encodeURIComponent(coverFilename)}" alt="${book.title} 封面" loading="lazy">`
                : `<div class="card-cover" style="display:flex;align-items:center;justify-content:center;background:var(--bg-hover);color:var(--text-muted);font-size:0.8rem;text-align:center;">暂无封面</div>`;

            const ratingHtml = book.rating ? `豆瓣评分: ${book.rating}` : '暂无评分';
            const reasonHtml = book.reason ? book.reason : '<em>无判定理由</em>';
            const suggestedCatText = book.suggested_category ? `建议分类: ${book.suggested_category}` : '分类不明确';

            let suggestedCatBlock = `<span class="card-tag tag-suggested">${suggestedCatText}</span>`;
            if (book.suggested_category) {
                suggestedCatBlock = `
                    <span class="card-tag tag-suggested interactive" data-id="${book.id}">
                        ${suggestedCatText} ▾
                        <div class="popover-menu">
                            <button class="popover-item accept" data-id="${book.id}" data-cat="${esc(book.suggested_category)}">
                                <span>✅</span> 接受建议
                            </button>
                            <button class="popover-item ignore">
                                <span>✖️</span> 忽略建议
                            </button>
                            <button class="popover-item reclassify" data-id="${book.id}">
                                <span>🔄</span> 重新分类
                            </button>
                        </div>
                    </span>
                `;
            }

            return `
                <div class="other-book-card">
                    <div class="card-header">
                        ${coverHtml}
                        <div class="card-info">
                            <h3 class="card-title">${book.title || '未知书名'}</h3>
                            <p class="card-author">${book.author || '未知作者'}</p>
                            <span class="card-rating">${ratingHtml}</span>
                        </div>
                    </div>
                    
                    <div class="card-reason-section">
                        <span class="reason-label">DeepSeek 判定理由</span>
                        <div class="reason-text">${reasonHtml}</div>
                    </div>
                    
                    <div class="card-footer">
                        <div class="card-tags">
                            ${isCategoryMatched ? `<span class="card-tag tag-philosophy">✓ 属于${rootCategory || '该分类'}范畴</span>` : `<span class="card-tag">✗ 非${rootCategory || '该分类'}范畴</span>`}
                            ${suggestedCatBlock}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Event Listeners Configuration
    function setupEventListeners() {
        // Filter: Category only
        elements.filterCategory.addEventListener('change', (e) => {
            state.filters.onlyCategory = e.target.checked;
            applyFilters();
        });

        // Filter: Search
        let searchTimeout;
        elements.searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                state.filters.searchQuery = e.target.value;
                applyFilters();
            }, 300);
        });

        // Close popovers when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.tag-suggested.interactive')) {
                document.querySelectorAll('.tag-suggested.show-popover').forEach(el => el.classList.remove('show-popover'));
            }
        });

        // Interactive tag and popover actions
        elements.grid.addEventListener('click', async (e) => {
            // 1. Toggle popover
            const tag = e.target.closest('.tag-suggested.interactive');
            if (tag && !e.target.closest('.popover-menu')) {
                // Close others
                document.querySelectorAll('.tag-suggested.show-popover').forEach(el => {
                    if (el !== tag) el.classList.remove('show-popover');
                });
                tag.classList.toggle('show-popover');
                return;
            }

            // 2. Popover Actions
            if (e.target.closest('.popover-item')) {
                const btn = e.target.closest('.popover-item');
                const tagParent = btn.closest('.tag-suggested.interactive');

                if (btn.classList.contains('ignore')) {
                    if (tagParent) tagParent.classList.remove('show-popover');
                    return;
                }

                const bookId = parseInt(btn.dataset.id);

                // Keep original text to restore on failure
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<span>⏳</span> 处理中...';
                btn.disabled = true;

                try {
                    if (btn.classList.contains('accept')) {
                        const suggestedCat = btn.dataset.cat;
                        const response = await fetch('/api/accept_suggestion', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ book_id: bookId, suggested_category: suggestedCat })
                        });
                        const result = await response.json();
                        if (!result.success) throw new Error(result.error || 'Unknown error');
                    }
                    else if (btn.classList.contains('reclassify')) {
                        const response = await fetch('/api/reclassify', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ book_id: bookId })
                        });
                        const result = await response.json();
                        if (!result.success) throw new Error(result.error || 'Unknown error');
                    }

                    // On success, remove book and re-render
                    state.books = state.books.filter(b => b.id !== bookId);
                    applyFilters();

                } catch (err) {
                    console.error('Action failed:', err);
                    alert('操作失败: ' + err.message);
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                }
            }
        });
    }

    // Initialization
    initTheme();
    setupEventListeners();
    fetchBooks();
});
