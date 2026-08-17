(function() {
    if (document.getElementById('tw45-donate-widget-container')) return;

    // Detect user language (Browser language + Geo IP fallback)
    let userLang = localStorage.getItem('tw45_lang');
    if (!userLang) {
        const navLang = (navigator.language || navigator.userLanguage || '').toLowerCase();
        userLang = navLang.startsWith('id') ? 'id' : 'en';
    }

    const translations = {
        id: {
            btn: "Dukung / Donate",
            title: "💖 Dukung Karya Ini",
            desc: "Terima kasih telah menggunakan aplikasi ini! Dukungan kamu sangat berarti untuk pengembangan proyek open-source & robotika ini.",
            sociabuzz: "⚡ SociaBuzz (Global / PayPal / Card / QRIS)",
            saweria: "💛 Saweria (QRIS / DANA / OVO)",
            trakteer: "☕ Trakteer (Kopi & Dukungan)",
            linktree: "🌳 Linktree Tri Wahyu (Semua Link)",
            footer: "Dibuat oleh Tri Wahyu (@triwahyu45)"
        },
        en: {
            btn: "Support / Donate",
            title: "💖 Support This Project",
            desc: "Thank you for using this app! Your support means a lot for the ongoing development of this robotics & AI project.",
            sociabuzz: "⚡ SociaBuzz (International / PayPal / Card / QRIS)",
            saweria: "💛 Saweria (QRIS / Local E-Wallet)",
            trakteer: "☕ Trakteer (Coffee & Support)",
            linktree: "🌳 Linktree Tri Wahyu (All Links)",
            footer: "Created by Tri Wahyu (@triwahyu45)"
        }
    };

    const style = document.createElement('style');
    style.innerHTML = `
        .tw45-donate-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 999999;
            background: linear-gradient(135deg, #2563eb, #3b82f6, #ec4899);
            color: #fff;
            border: none;
            padding: 10px 18px;
            border-radius: 30px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px rgba(37, 99, 235, 0.45);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            user-select: none;
        }
        .tw45-donate-btn:hover {
            transform: translateY(-3px) scale(1.05);
            box-shadow: 0 12px 30px rgba(236, 72, 153, 0.6);
        }
        .tw45-donate-btn:active {
            transform: translateY(0) scale(0.98);
        }
        .tw45-donate-overlay {
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(6px);
            z-index: 999998;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.3s ease, visibility 0.3s ease;
        }
        .tw45-donate-overlay.active {
            opacity: 1;
            visibility: visible;
        }
        .tw45-donate-modal {
            position: fixed;
            bottom: 80px;
            right: 20px;
            width: 340px;
            max-width: calc(100vw - 40px);
            background: #18191c;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 20px;
            padding: 22px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.75);
            z-index: 999999;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: #fff;
            opacity: 0;
            visibility: hidden;
            transform: translateY(20px) scale(0.95);
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        .tw45-donate-modal.active {
            opacity: 1;
            visibility: visible;
            transform: translateY(0) scale(1);
        }
        .tw45-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }
        .tw45-modal-title {
            font-size: 16px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 6px;
            color: #fff;
        }
        .tw45-header-right {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .tw45-lang-toggle {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #fff;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        .tw45-lang-toggle:hover {
            background: rgba(255, 255, 255, 0.25);
        }
        .tw45-close-btn {
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: #aaa;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            transition: background 0.2s;
        }
        .tw45-close-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            color: #fff;
        }
        .tw45-modal-desc {
            font-size: 12px;
            color: #88888e;
            margin-bottom: 16px;
            line-height: 1.4;
        }
        .tw45-donate-links {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .tw45-donate-link {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            border-radius: 12px;
            text-decoration: none;
            color: #fff;
            font-size: 13px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .tw45-donate-link:hover {
            transform: translateX(4px);
        }
        .tw45-link-sociabuzz {
            background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 50%, #60a5fa 100%);
            color: #fff;
            box-shadow: 0 4px 14px rgba(29, 78, 216, 0.35);
        }
        .tw45-link-saweria {
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: #111;
        }
        .tw45-link-trakteer {
            background: linear-gradient(135deg, #e11d48 0%, #be123c 100%);
            color: #fff;
        }
        .tw45-link-linktree {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: #fff;
        }
        .tw45-footer-tag {
            margin-top: 14px;
            text-align: center;
            font-size: 11px;
            color: #666;
        }
    `;
    document.head.appendChild(style);

    const container = document.createElement('div');
    container.id = 'tw45-donate-widget-container';
    container.innerHTML = `
        <div class="tw45-donate-overlay" id="tw45-overlay"></div>
        <button class="tw45-donate-btn" id="tw45-btn">
            ❤️ <span id="tw45-btn-txt"></span>
        </button>
        <div class="tw45-donate-modal" id="tw45-modal">
            <div class="tw45-modal-header">
                <div class="tw45-modal-title" id="tw45-title"></div>
                <div class="tw45-header-right">
                    <button class="tw45-lang-toggle" id="tw45-lang-btn"></button>
                    <button class="tw45-close-btn" id="tw45-close">✕</button>
                </div>
            </div>
            <div class="tw45-modal-desc" id="tw45-desc"></div>
            <div class="tw45-donate-links">
                <a href="https://sociabuzz.com/triwahyu45" target="_blank" rel="noopener noreferrer" class="tw45-donate-link tw45-link-sociabuzz">
                    <span id="tw45-sociabuzz-txt"></span> ➔
                </a>
                <a href="https://saweria.co/triwahyu45" target="_blank" rel="noopener noreferrer" class="tw45-donate-link tw45-link-saweria">
                    <span id="tw45-saweria-txt"></span> ➔
                </a>
                <a href="https://trakteer.id/triwahyu45" target="_blank" rel="noopener noreferrer" class="tw45-donate-link tw45-link-trakteer">
                    <span id="tw45-trakteer-txt"></span> ➔
                </a>
                <a href="https://linktr.ee/triwahyu45" target="_blank" rel="noopener noreferrer" class="tw45-donate-link tw45-link-linktree">
                    <span id="tw45-linktree-txt"></span> ➔
                </a>
            </div>
            <div class="tw45-footer-tag" id="tw45-footer-txt"></div>
        </div>
    `;
    document.body.appendChild(container);

    function updateWidgetText() {
        const t = translations[userLang] || translations.id;
        document.getElementById('tw45-btn-txt').innerText = t.btn;
        document.getElementById('tw45-title').innerText = t.title;
        document.getElementById('tw45-desc').innerText = t.desc;
        document.getElementById('tw45-sociabuzz-txt').innerText = t.sociabuzz;
        document.getElementById('tw45-saweria-txt').innerText = t.saweria;
        document.getElementById('tw45-trakteer-txt').innerText = t.trakteer;
        document.getElementById('tw45-linktree-txt').innerText = t.linktree;
        document.getElementById('tw45-footer-txt').innerText = t.footer;
        document.getElementById('tw45-lang-btn').innerText = userLang === 'id' ? '🇬🇧 EN' : '🇮🇩 ID';
    }

    // Geo IP Lookup Fallback
    fetch('https://ipapi.co/json/')
        .then(res => res.json())
        .then(data => {
            if (!localStorage.getItem('tw45_lang') && data && data.country_code) {
                userLang = data.country_code === 'ID' ? 'id' : 'en';
                updateWidgetText();
            }
        })
        .catch(() => {});

    updateWidgetText();

    const btn = document.getElementById('tw45-btn');
    const modal = document.getElementById('tw45-modal');
    const overlay = document.getElementById('tw45-overlay');
    const closeBtn = document.getElementById('tw45-close');
    const langBtn = document.getElementById('tw45-lang-btn');

    function toggleModal(show) {
        if (show) {
            modal.classList.add('active');
            overlay.classList.add('active');
        } else {
            modal.classList.remove('active');
            overlay.classList.remove('active');
        }
    }

    btn.addEventListener('click', () => toggleModal(!modal.classList.contains('active')));
    closeBtn.addEventListener('click', () => toggleModal(false));
    overlay.addEventListener('click', () => toggleModal(false));

    langBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        userLang = userLang === 'id' ? 'en' : 'id';
        localStorage.setItem('tw45_lang', userLang);
        updateWidgetText();
    });
})();
