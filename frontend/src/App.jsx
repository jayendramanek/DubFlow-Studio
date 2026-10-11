import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Film,
  Plus,
  ExternalLink,
  Edit2,
  Trash2,
  Info,
  RefreshCw,
  LogOut,
  Play,
  Download,
  Lock,
  Mail,
  Eye,
  EyeOff,
  ArrowLeft,
  Check,
  Cpu,
  Layers,
  Sparkles,
  Youtube,
  Scissors
} from 'lucide-react';

// Dubbing Languages Metadata
const LANGUAGES = [
  {
    code: "es",
    name: "Spanish",
    flag: "🇪🇸",
    native: "Español",
    badge: "EN ESPAÑOL",
    color: "#f97316",
    voices: [
      { id: "es-ES-AlvaroNeural", name: "Alvaro (Spain - Dramatic)", gender: "male", desc: "Recap narrator" },
      { id: "es-MX-JorgeNeural", name: "Jorge (Mexico - Energetic)", gender: "male", desc: "Action narrator" },
      { id: "es-ES-ElviraNeural", name: "Elvira (Spain - Expressive)", gender: "female", desc: "Clear & serious" },
      { id: "es-MX-DaliaNeural", name: "Dalia (Mexico - Smooth)", gender: "female", desc: "Natural tone" },
    ]
  },
  {
    code: "ta",
    name: "Tamil",
    flag: "🇮🇳",
    native: "தமிழ்",
    badge: "TAMIL RECAP",
    color: "#10b981",
    voices: [
      { id: "ta-IN-ValluvarNeural", name: "Valluvar (India - Dramatic)", gender: "male", desc: "Powerful narrator" },
      { id: "ta-IN-PallaviNeural", name: "Pallavi (India - Expressive)", gender: "female", desc: "Smooth storytelling" },
    ]
  },
  {
    code: "te",
    name: "Telugu",
    flag: "🇮🇳",
    native: "తెలుగు",
    badge: "TELUGU RECAP",
    color: "#06b6d4",
    voices: [
      { id: "te-IN-MohanNeural", name: "Mohan (India - Energetic)", gender: "male", desc: "Recap narrator" },
      { id: "te-IN-ShrutiNeural", name: "Shruti (India - Smooth)", gender: "female", desc: "Natural tone" },
    ]
  },
  {
    code: "bn",
    name: "Bengali",
    flag: "🇮🇳",
    native: "বাংলা",
    badge: "BENGALI RECAP",
    color: "#3b82f6",
    voices: [
      { id: "bn-IN-BashkarNeural", name: "Bashkar (India - Dramatic)", gender: "male", desc: "Storytelling tone" },
      { id: "bn-BD-PradeepNeural", name: "Pradeep (Bangladesh - Dhaka)", gender: "male", desc: "Natural recap tone" },
      { id: "bn-IN-TanishaaNeural", name: "Tanishaa (India - Expressive)", gender: "female", desc: "Smooth narrator" },
    ]
  },
  {
    code: "hi",
    name: "Hindi",
    flag: "🇮🇳",
    native: "हिन्दी",
    badge: "HINDI RECAP",
    color: "#ec4899",
    voices: [
      { id: "hi-IN-MadhurNeural", name: "Madhur (India - Cinematic)", gender: "male", desc: "Deep narrator" },
      { id: "hi-IN-SwaraNeural", name: "Swara (India - Professional)", gender: "female", desc: "Clear voice" },
    ]
  },
  {
    code: "kn",
    name: "Kannada",
    flag: "🇮🇳",
    native: "ಕನ್ನಡ",
    badge: "KANNADA RECAP",
    color: "#8b5cf6",
    voices: [
      { id: "kn-IN-GaganNeural", name: "Gagan (India - Storyteller)", gender: "male", desc: "Clear narrator" },
      { id: "kn-IN-SapnaNeural", name: "Sapna (India - Expressive)", gender: "female", desc: "Storytelling tone" },
    ]
  },
  {
    code: "ml",
    name: "Malayalam",
    flag: "🇮🇳",
    native: "മലയാളം",
    badge: "MALAYALAM RECAP",
    color: "#14b8a6",
    voices: [
      { id: "ml-IN-MidhunNeural", name: "Midhun (India - Cinematic)", gender: "male", desc: "Calm voice" },
      { id: "ml-IN-SobhanaNeural", name: "Sobhana (India - Smooth)", gender: "female", desc: "Narrative tone" },
    ]
  },
  {
    code: "mr",
    name: "Marathi",
    flag: "🇮🇳",
    native: "मराठी",
    badge: "MARATHI RECAP",
    color: "#f59e0b",
    voices: [
      { id: "mr-IN-ManoharNeural", name: "Manohar (India - Expressive)", gender: "male", desc: "Dramatic tone" },
      { id: "mr-IN-AarohiNeural", name: "Aarohi (India - Clear)", gender: "female", desc: "Smooth narrative" },
    ]
  },
  {
    code: "id",
    name: "Indonesian",
    flag: "🇮🇩",
    native: "Bahasa",
    badge: "BAHASA INDONESIA",
    color: "#ef4444",
    voices: [
      { id: "id-ID-ArdiNeural", name: "Ardi (Indonesia - Alur Cerita)", gender: "male", desc: "Manhwa recap narrator" },
      { id: "id-ID-GadisNeural", name: "Gadis (Indonesia - Smooth)", gender: "female", desc: "Natural narration" },
    ]
  },
  {
    code: "pt",
    name: "Portuguese",
    flag: "🇧🇷",
    native: "Português",
    badge: "EM PORTUGUÊS",
    color: "#22c55e",
    voices: [
      { id: "pt-BR-AntonioNeural", name: "Antonio (Brazil - Resumo)", gender: "male", desc: "Manhwa narrator" },
      { id: "pt-BR-FranciscaNeural", name: "Francisca (Brazil - Expressive)", gender: "female", desc: "Expressive voice" },
    ]
  },
  {
    code: "fr",
    name: "French",
    flag: "🇫🇷",
    native: "Français",
    badge: "EN FRANÇAIS",
    color: "#6366f1",
    voices: [
      { id: "fr-FR-HenriNeural", name: "Henri (France - Cinematic)", gender: "male", desc: "Serious narrator" },
      { id: "fr-FR-DeniseNeural", name: "Denise (France - Expressive)", gender: "female", desc: "Engaging voice" },
    ]
  },
  {
    code: "vi",
    name: "Vietnamese",
    flag: "🇻🇳",
    native: "Tiếng Việt",
    badge: "THUYẾT MINH",
    color: "#e11d48",
    voices: [
      { id: "vi-VN-NamMinhNeural", name: "Nam Minh (Vietnam - Review)", gender: "male", desc: "Recap storyteller" },
      { id: "vi-VN-HoaiMyNeural", name: "Hoài My (Vietnam - Expressive)", gender: "female", desc: "Clear tone" },
    ]
  },
  {
    code: "ar",
    name: "Arabic",
    flag: "🇸🇦",
    native: "العربية",
    badge: "بالعربية",
    color: "#d97706",
    voices: [
      { id: "ar-SA-HamedNeural", name: "Hamed (Saudi Arabia - Dramatic)", gender: "male", desc: "Deep narrator" },
      { id: "ar-EG-SalmaNeural", name: "Salma (Egypt - Storyteller)", gender: "female", desc: "Expressive voice" },
    ]
  },
  {
    code: "de",
    name: "German",
    flag: "🇩🇪",
    native: "Deutsch",
    badge: "AUF DEUTSCH",
    color: "#eab308",
    voices: [
      { id: "de-DE-ConradNeural", name: "Conrad (Germany - Deep)", gender: "male", desc: "Anime recap narrator" },
      { id: "de-DE-KatjaNeural", name: "Katja (Germany - Clear)", gender: "female", desc: "Storytelling tone" },
    ]
  },
  {
    code: "ru",
    name: "Russian",
    flag: "🇷🇺",
    native: "Русский",
    badge: "НА РУССКОМ",
    color: "#0284c7",
    voices: [
      { id: "ru-RU-DmitryNeural", name: "Dmitry (Russia - Dramatic)", gender: "male", desc: "Manhwa recap voice" },
      { id: "ru-RU-SvetlanaNeural", name: "Svetlana (Russia - Emotional)", gender: "female", desc: "Expressive narrator" },
    ]
  },
  {
    code: "ja",
    name: "Japanese",
    flag: "🇯🇵",
    native: "日本語",
    badge: "日本語吹き替え",
    color: "#f43f5e",
    voices: [
      { id: "ja-JP-KeitaNeural", name: "Keita (Japan - Anime)", gender: "male", desc: "Anime style male" },
      { id: "ja-JP-NanamiNeural", name: "Nanami (Japan - Anime)", gender: "female", desc: "Expressive voice" },
    ]
  }
];

const LANG_MAP = LANGUAGES.reduce((acc, l) => ({ ...acc, [l.code]: l }), {});

// Interactive Language Pie Chart
function LanguagePieChart({ data = {}, size = 260 }) {
  const [hoveredSlice, setHoveredSlice] = useState(null);

  const entries = Object.entries(data).map(([code, count]) => {
    const meta = LANG_MAP[code] || { name: code.toUpperCase(), flag: "🌐", color: "#6366f1" };
    return {
      code,
      name: meta.name,
      flag: meta.flag,
      color: meta.color || "#6366f1",
      value: count
    };
  }).sort((a, b) => b.value - a.value);

  const total = entries.reduce((s, e) => s + e.value, 0);

  if (total === 0 || entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-500">
        <p>No video conversions recorded yet.</p>
      </div>
    );
  }

  const innerRadius = 60;
  const outerRadius = 95;
  const cx = size / 2;
  const cy = size / 2;

  let currentAngle = 0;
  const slices = entries.map((entry) => {
    const fraction = entry.value / total;
    const angle = fraction * 2 * Math.PI;
    const startAngle = currentAngle;
    const endAngle = currentAngle + angle;
    currentAngle += angle;

    const x1 = cx + outerRadius * Math.cos(startAngle - Math.PI / 2);
    const y1 = cy + outerRadius * Math.sin(startAngle - Math.PI / 2);
    const x2 = cx + outerRadius * Math.cos(endAngle - Math.PI / 2);
    const y2 = cy + outerRadius * Math.sin(endAngle - Math.PI / 2);

    const x3 = cx + innerRadius * Math.cos(endAngle - Math.PI / 2);
    const y3 = cy + innerRadius * Math.sin(endAngle - Math.PI / 2);
    const x4 = cx + innerRadius * Math.cos(startAngle - Math.PI / 2);
    const y4 = cy + innerRadius * Math.sin(startAngle - Math.PI / 2);

    const largeArc = fraction > 0.5 ? 1 : 0;
    const pathData = `
      M ${x1} ${y1}
      A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${x2} ${y2}
      L ${x3} ${y3}
      A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${x4} ${y4}
      Z
    `;

    return {
      ...entry,
      pathData,
      percentage: Math.round(fraction * 100)
    };
  });

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6 justify-center">
      <div className="relative flex items-center justify-center">
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {slices.map((slice) => (
            <path
              key={slice.code}
              d={slice.pathData}
              fill={slice.color}
              stroke="#13151b"
              strokeWidth="3"
              className="transition-transform duration-200 cursor-pointer hover:opacity-90"
              onMouseEnter={() => setHoveredSlice(slice)}
              onMouseLeave={() => setHoveredSlice(null)}
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          {hoveredSlice ? (
            <>
              <span className="text-xl">{hoveredSlice.flag}</span>
              <span className="text-xs font-semibold text-slate-300">{hoveredSlice.name}</span>
              <span className="text-sm font-bold text-white">{hoveredSlice.value} vids ({hoveredSlice.percentage}%)</span>
            </>
          ) : (
            <>
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Total</span>
              <span className="text-2xl font-black text-white">{total}</span>
              <span className="text-[10px] text-gray-400">Conversions</span>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2 max-h-56 overflow-y-auto pr-2 text-xs w-full sm:w-48">
        {slices.map(s => (
          <div
            key={s.code}
            onMouseEnter={() => setHoveredSlice(s)}
            onMouseLeave={() => setHoveredSlice(null)}
            className={`flex items-center justify-between p-1.5 rounded-lg transition cursor-pointer ${hoveredSlice?.code === s.code ? 'bg-surface-800' : 'hover:bg-surface-850'}`}
          >
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }}></span>
              <span>{s.flag}</span>
              <span className="font-medium text-slate-200">{s.name}</span>
            </div>
            <span className="font-bold text-slate-400">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Apple Silicon RAM Donut Chart
function RamDonutChart({ ram = { percent: 0, used_gb: 0, free_gb: 0, total_gb: 0 }, onRefresh }) {
  const radius = 80;
  const strokeWidth = 20;
  const circumference = 2 * Math.PI * radius;
  const percent = Math.min(100, Math.max(0, ram.percent || 0));
  const strokeDashoffset = circumference - (percent / 100) * circumference;

  return (
    <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
      <div className="relative flex items-center justify-center">
        <svg width="220" height="220" viewBox="0 0 220 220" className="transform -rotate-90">
          <circle
            cx="110"
            cy="110"
            r={radius}
            stroke="#1e212b"
            strokeWidth={strokeWidth}
            fill="transparent"
          />
          <circle
            cx="110"
            cy="110"
            r={radius}
            stroke="url(#ramGradVite)"
            strokeWidth={strokeWidth}
            fill="transparent"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="transition-all duration-1000 ease-out"
          />
          <defs>
            <linearGradient id="ramGradVite" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#6366f1" />
              <stop offset="60%" stopColor="#818cf8" />
              <stop offset="100%" stopColor="#ec4899" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-3xl font-black text-white">{percent}%</span>
          <span className="text-[11px] text-indigo-400 font-semibold tracking-wider uppercase">RAM Used</span>
        </div>
      </div>

      <div className="flex flex-col gap-3 text-xs w-full sm:w-44">
        <div className="p-2.5 rounded-lg bg-surface-850 border border-white/5">
          <div className="text-gray-400">Used Memory</div>
          <div className="text-base font-bold text-indigo-300">{ram.used_gb} GB</div>
        </div>
        <div className="p-2.5 rounded-lg bg-surface-850 border border-white/5">
          <div className="text-gray-400">Free / Available</div>
          <div className="text-base font-bold text-emerald-400">{ram.free_gb} GB</div>
        </div>
        <div className="flex items-center justify-between text-gray-400 px-1">
          <span>Total Unified:</span>
          <span className="font-bold text-white">{ram.total_gb} GB</span>
        </div>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-surface-800 hover:bg-surface-700 text-slate-300 font-medium transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh RAM</span>
          </button>
        )}
      </div>
    </div>
  );
}

// Login Screen
function LoginScreen({ onLoginSuccess }) {
  const [email, setEmail] = useState("admin@admin.com");
  const [password, setPassword] = useState("admin@1994");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);

    const expectedEmail = import.meta.env?.VITE_ADMIN_EMAIL || window.ENV?.VITE_ADMIN_EMAIL || "admin@admin.com";
    const expectedPassword = import.meta.env?.VITE_ADMIN_PASSWORD || window.ENV?.VITE_ADMIN_PASSWORD || "admin@1994";

    setTimeout(() => {
      if (email.trim().toLowerCase() === expectedEmail.toLowerCase() && password === expectedPassword) {
        localStorage.setItem("admin_auth", "true");
        localStorage.setItem("admin_user", JSON.stringify({ email: email.trim(), role: "Super Admin" }));
        onLoginSuccess();
      } else {
        setError("Invalid email or password. Please verify credentials in .env.");
      }
      setIsSubmitting(false);
    }, 400);
  };

  const handleQuickFill = () => {
    setEmail("admin@admin.com");
    setPassword("admin@1994");
    setError("");
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden bg-surface-950 text-slate-100">
      <div className="w-full max-w-md glass-card rounded-2xl p-8 shadow-2xl relative z-10 border border-white/10">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-tr from-cyan-500 via-brand-500 to-indigo-600 shadow-xl shadow-cyan-500/25 mb-4 border border-white/10">
            <span className="text-xl font-black text-white tracking-tighter">DF</span>
          </div>
          <h1 className="text-2xl font-black tracking-tight text-white">DubFlow Studio</h1>
          <p className="text-xs text-slate-400 mt-1">Universal AI Video Dubbing & Localization Portal</p>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2">
              Admin Email
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                <Mail className="w-4 h-4" />
              </div>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@admin.com"
                className="w-full pl-11 pr-4 py-2.5 rounded-xl bg-surface-900 border border-slate-700 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-slate-100 text-sm transition outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2">
              Password
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                <Lock className="w-4 h-4" />
              </div>
              <input
                type={showPassword ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-11 pr-11 py-2.5 rounded-xl bg-surface-900 border border-slate-700 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-slate-100 text-sm transition outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-200"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Default: admin@admin.com / admin@1994</span>
            <button
              type="button"
              onClick={handleQuickFill}
              className="text-brand-400 hover:text-brand-300 underline font-medium"
            >
              Quick Autofill
            </button>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-brand-600 via-indigo-600 to-cyan-500 hover:opacity-95 text-white font-bold text-sm shadow-lg shadow-brand-500/25 transition transform active:scale-95 disabled:opacity-50"
          >
            {isSubmitting ? "Authenticating..." : "Sign In to DubFlow Studio"}
          </button>
        </form>
      </div>
    </div>
  );
}

// Main App Component
export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return localStorage.getItem("admin_auth") === "true";
  });

  const [activeTab, setActiveTab] = useState("dashboard"); // 'dashboard' | 'videos' | 'video_details'
  const [selectedVideoId, setSelectedVideoId] = useState(null);
  const [systemStats, setSystemStats] = useState(null);
  const [videosList, setVideosList] = useState([]);
  const [isLoadingVideos, setIsLoadingVideos] = useState(false);

  // Modals
  const [isAddVideoModalOpen, setIsAddVideoModalOpen] = useState(false);

  // YTD state: channels, stats, selected channel, modals
  const [ytdChannels, setYtdChannels] = useState([]);
  const [ytdStats, setYtdStats] = useState(null);
  const [isLoadingYtd, setIsLoadingYtd] = useState(false);
  const [selectedChannelId, setSelectedChannelId] = useState(null);
  const [isAddChannelModalOpen, setIsAddChannelModalOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState(null);
  const [downloadModalVideo, setDownloadModalVideo] = useState(null);

  const fetchStats = async () => {
    try {
      const res = await fetch("/api/system/stats");
      if (res.ok) {
        const data = await res.json();
        setSystemStats(data);
      }
    } catch (e) {
      console.error("Stats fetch error:", e);
    }
  };

  const fetchVideos = async () => {
    setIsLoadingVideos(true);
    try {
      const res = await fetch("/api/videos");
      if (res.ok) {
        const data = await res.json();
        setVideosList(data);
      }
    } catch (e) {
      console.error("Videos fetch error:", e);
    } finally {
      setIsLoadingVideos(false);
    }
  };

  const fetchYtdChannels = async () => {
    setIsLoadingYtd(true);
    try {
      const res = await fetch("/api/ytd/channels");
      if (res.ok) setYtdChannels(await res.json());
    } catch (err) {
      console.error("YTD channels fetch error:", err);
    } finally {
      setIsLoadingYtd(false);
    }
  };

  const fetchYtdStats = async () => {
    try {
      const res = await fetch("/api/ytd/stats");
      if (res.ok) setYtdStats(await res.json());
    } catch (err) {
      console.error("YTD stats fetch error:", err);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      fetchStats();
      fetchVideos();
      fetchYtdChannels();
      fetchYtdStats();
      const interval = setInterval(() => {
        fetchStats();
        fetchYtdStats();
      }, 8000);
      return () => clearInterval(interval);
    }
  }, [isAuthenticated]);

  const handleLogout = () => {
    localStorage.removeItem("admin_auth");
    localStorage.removeItem("admin_user");
    setIsAuthenticated(false);
  };

  const handleOpenVideoDetails = (vidId) => {
    setSelectedVideoId(vidId);
    setActiveTab("video_details");
  };

  const handleDeleteVideo = async (videoId, title) => {
    const promptText = title
      ? `Are you sure you want to delete video "${title}"? This will permanently delete all associated conversions and files.`
      : "Are you sure you want to delete this video project? This will permanently delete all associated conversions and files.";
    if (window.confirm(promptText)) {
      try {
        const res = await fetch(`/api/videos/${videoId}`, { method: "DELETE" });
        if (res.ok) {
          fetchVideos();
          fetchStats();
          if (selectedVideoId === videoId) {
            setSelectedVideoId(null);
            setActiveTab("videos");
          }
        } else {
          const err = await res.json().catch(() => ({}));
          alert("Failed to delete video: " + (err.detail || "Server error"));
        }
      } catch (err) {
        alert("Error deleting video: " + err.message);
      }
    }
  };

  const handleDeleteConversion = async (jobId, partName) => {
    const name = partName || jobId;
    if (window.confirm(`Are you sure you want to delete converted video "${name}"? This will permanently delete its media files.`)) {
      try {
        const res = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
        if (res.ok) {
          fetchVideos();
          fetchStats();
        } else {
          const err = await res.json().catch(() => ({}));
          alert("Failed to delete converted video: " + (err.detail || "Server error"));
        }
      } catch (err) {
        alert("Error deleting conversion: " + err.message);
      }
    }
  };

  const handleSyncChannel = async (channelId) => {
    try {
      const res = await fetch(`/api/ytd/channels/${channelId}/sync`, { method: "POST" });
      if (res.ok) {
        fetchYtdChannels();
        fetchYtdStats();
      } else {
        const err = await res.json().catch(() => ({}));
        alert("Failed to sync channel: " + (err.detail || "Server error"));
      }
    } catch (err) {
      alert("Error syncing channel: " + err.message);
    }
  };

  const handleDeleteChannel = async (channelId, title) => {
    const promptText = title
      ? `Are you sure you want to delete channel "${title}" and all its videos/files?`
      : "Are you sure you want to delete this channel and its videos?";
    if (window.confirm(promptText)) {
      try {
        const res = await fetch(`/api/ytd/channels/${channelId}`, { method: "DELETE" });
        if (res.ok) {
          fetchYtdChannels();
          fetchYtdStats();
          if (selectedChannelId === channelId) {
            setSelectedChannelId(null);
            setActiveTab("ytd");
          }
        } else {
          const err = await res.json().catch(() => ({}));
          alert("Failed to delete channel: " + (err.detail || "Server error"));
        }
      } catch (err) {
        alert("Error deleting channel: " + err.message);
      }
    }
  };

  const handleDeleteYtdVideo = async (videoId, title) => {
    const promptText = title
      ? `Are you sure you want to delete video "${title}"? This will delete all downloaded files and blacklist it so it is never re-added on sync.`
      : "Are you sure you want to delete this video? It will never be re-added on sync.";
    if (window.confirm(promptText)) {
      try {
        const res = await fetch(`/api/ytd/videos/${videoId}`, { method: "DELETE" });
        if (res.ok) {
          fetchYtdChannels();
          fetchYtdStats();
          return true;
        } else {
          const err = await res.json().catch(() => ({}));
          alert("Failed to delete video: " + (err.detail || "Server error"));
          return false;
        }
      } catch (err) {
        alert("Error deleting video: " + err.message);
        return false;
      }
    }
    return false;
  };

  if (!isAuthenticated) {
    return <LoginScreen onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <div className="flex h-screen bg-surface-950 text-slate-100 overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 bg-surface-900 border-r border-slate-800 flex flex-col justify-between z-20">
        <div>
          {/* Brand Header */}
          <div className="p-6 border-b border-slate-800/80 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 via-brand-500 to-indigo-600 flex items-center justify-center font-black text-white text-base shadow-lg shadow-cyan-500/20 border border-white/10">
              DF
            </div>
            <div>
              <h1 className="font-black text-base tracking-tight text-white leading-tight">DubFlow</h1>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 uppercase tracking-widest">
                Studio Admin
              </span>
            </div>
          </div>

          {/* Navigation Menu */}
          <nav className="p-4 space-y-1.5">
            <button
              type="button"
              onClick={() => { setActiveTab("dashboard"); setSelectedVideoId(null); }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl font-semibold text-sm transition ${activeTab === 'dashboard' ? 'bg-gradient-to-r from-brand-600 to-indigo-600 text-white shadow-lg shadow-brand-500/25' : 'text-slate-300 hover:bg-surface-850 hover:text-white'}`}
            >
              <LayoutDashboard className="w-4 h-4" />
              <span>Dashboard</span>
            </button>

            <button
              type="button"
              onClick={() => { setActiveTab("videos"); }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl font-semibold text-sm transition ${activeTab === 'videos' || activeTab === 'video_details' ? 'bg-gradient-to-r from-brand-600 to-indigo-600 text-white shadow-lg shadow-brand-500/25' : 'text-slate-300 hover:bg-surface-850 hover:text-white'}`}
            >
              <Film className="w-4 h-4" />
              <span>Videos</span>
              {videosList.length > 0 && (
                <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-black/30 text-slate-200">
                  {videosList.length}
                </span>
              )}
            </button>

            <button
              type="button"
              onClick={() => { setActiveTab("ytd"); setSelectedChannelId(null); }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl font-semibold text-sm transition ${activeTab === 'ytd' || activeTab === 'ytd_channel_details' ? 'bg-gradient-to-r from-red-600 to-rose-600 text-white shadow-lg shadow-red-500/25' : 'text-slate-300 hover:bg-surface-850 hover:text-white'}`}
            >
              <Youtube className="w-4 h-4" />
              <span>YTD</span>
              {ytdChannels.length > 0 && (
                <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-black/30 text-slate-200">
                  {ytdChannels.length}
                </span>
              )}
            </button>
          </nav>
        </div>

        {/* Bottom Hardware Widget & User Card */}
        <div className="p-4 border-t border-slate-800 space-y-3">
          {/* Mini RAM Status */}
          <div className="p-3 rounded-xl bg-surface-850 border border-white/5 text-xs">
            <div className="flex items-center justify-between text-slate-400 mb-1.5">
              <span className="font-semibold text-slate-300">
                {systemStats?.hardware?.os === 'Darwin' ? 'System RAM' : 'Server Memory'}
              </span>
              <span className="font-bold text-indigo-400">{systemStats?.ram?.percent || 0}%</span>
            </div>
            <div className="w-full bg-surface-900 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-gradient-to-r from-brand-500 to-indigo-400 h-1.5 rounded-full transition-all duration-500"
                style={{ width: `${systemStats?.ram?.percent || 0}%` }}
              ></div>
            </div>
            <div className="flex justify-between items-center mt-2 text-[10px] text-slate-500">
              <span>{systemStats?.ram?.used_gb || 0} GB Used</span>
              <span>{systemStats?.ram?.total_gb || 0} GB Total</span>
            </div>
          </div>

          {/* User Profile Card */}
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2.5 overflow-hidden">
              <div className="w-8 h-8 rounded-full bg-indigo-700 flex items-center justify-center font-bold text-xs text-white flex-shrink-0">
                AD
              </div>
              <div className="overflow-hidden">
                <p className="text-xs font-bold text-white truncate">admin@admin.com</p>
                <p className="text-[10px] text-slate-400">Super Admin</p>
              </div>
            </div>
            <button
              type="button"
              title="Log out"
              onClick={handleLogout}
              className="p-2 text-slate-400 hover:text-red-400 hover:bg-surface-850 rounded-lg transition"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-y-auto">
        {/* Top Header */}
        <header className="h-16 px-8 border-b border-slate-800 flex items-center justify-between flex-shrink-0 bg-surface-950/80 backdrop-blur sticky top-0 z-10">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-400">Admin</span>
            <span className="text-slate-600">/</span>
            <span className="font-bold text-white capitalize">
              {activeTab === 'video_details' ? 'Video Project Details' : activeTab === 'ytd_channel_details' ? 'Channel Videos' : activeTab === 'ytd' ? 'YouTube Downloader (YTD)' : activeTab}
            </span>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>{systemStats?.hardware?.engine_label || 'Acceleration Engine Active'}</span>
            </div>

            {activeTab === 'ytd' ? (
              <button
                type="button"
                onClick={() => setIsAddChannelModalOpen(true)}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-red-600 hover:bg-red-500 text-white font-bold text-xs transition shadow-md shadow-red-500/20"
              >
                <Plus className="w-4 h-4" />
                <span>Add New Channel</span>
              </button>
            ) : activeTab === 'ytd_channel_details' ? (
              <button
                type="button"
                onClick={() => { setActiveTab('ytd'); setSelectedChannelId(null); fetchYtdChannels(); }}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-200 font-bold text-xs transition border border-white/10"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Back to Channels</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setIsAddVideoModalOpen(true)}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs transition shadow-md shadow-brand-500/20"
              >
                <Plus className="w-4 h-4" />
                <span>Add New Video</span>
              </button>
            )}
          </div>
        </header>

        {/* View Component Render */}
        <div className="p-8 max-w-7xl w-full mx-auto">
          {activeTab === "dashboard" && (
            <div className="space-y-8">
              {/* Active Conversion Banner */}
              <div className="glass-card rounded-2xl p-6 border border-white/10">
                {systemStats?.active_jobs?.length > 0 ? (
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <span className="w-3 h-3 rounded-full bg-amber-400 animate-ping"></span>
                        <h2 className="text-base font-bold text-white">Active Video Conversion In Progress</h2>
                      </div>
                      <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-300 font-bold uppercase">
                        Running
                      </span>
                    </div>
                    <div className="w-full bg-surface-900 rounded-full h-3 overflow-hidden mb-2">
                      <div
                        className="bg-brand-500 h-3 rounded-full transition-all duration-300"
                        style={{ width: `${Math.round((systemStats.active_jobs[0].progress || 0) * 100)}%` }}
                      ></div>
                    </div>
                    <p className="text-xs text-slate-400">
                      Current Step: <strong className="text-slate-200">{systemStats.active_jobs[0].current_step}</strong>
                    </p>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                        <h2 className="text-base font-bold text-white">Conversion Engine Ready (Idle)</h2>
                      </div>
                      <p className="text-xs text-slate-400">
                        No active conversions executing. System is ready to convert new videos.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setIsAddVideoModalOpen(true)}
                      className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs transition"
                    >
                      Start New Video Conversion
                    </button>
                  </div>
                )}
              </div>

              {/* KPI Stat Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="glass-card rounded-2xl p-5 border border-white/5">
                  <div className="text-xs text-slate-400 uppercase font-semibold">Total Videos</div>
                  <div className="text-3xl font-black text-white mt-1">{systemStats?.counts?.total_videos || 0}</div>
                </div>
                <div className="glass-card rounded-2xl p-5 border border-white/5">
                  <div className="text-xs text-slate-400 uppercase font-semibold">Converted Parts</div>
                  <div className="text-3xl font-black text-indigo-400 mt-1">{systemStats?.counts?.total_conversions || 0}</div>
                </div>
                <div className="glass-card rounded-2xl p-5 border border-white/5">
                  <div className="text-xs text-slate-400 uppercase font-semibold">Currently Running</div>
                  <div className="text-3xl font-black text-amber-400 mt-1">{systemStats?.counts?.active_jobs || 0}</div>
                </div>
                <div className="glass-card rounded-2xl p-5 border border-white/5">
                  <div className="text-xs text-slate-400 uppercase font-semibold">Languages Converted</div>
                  <div className="text-3xl font-black text-emerald-400 mt-1">{systemStats?.counts?.total_languages || 0}</div>
                </div>
              </div>

              {/* Pie Charts */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="glass-card rounded-2xl p-6 border border-white/5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="font-bold text-base text-white">Converted Videos by Language</h3>
                    <span className="text-xs px-2.5 py-1 rounded-full bg-surface-850 text-indigo-400 font-bold border border-white/5">
                      Pie Chart
                    </span>
                  </div>
                  <LanguagePieChart data={systemStats?.languages || {}} size={240} />
                </div>

                <div className="glass-card rounded-2xl p-6 border border-white/5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="font-bold text-base text-white">System Memory (RAM)</h3>
                    <span className="text-xs px-2.5 py-1 rounded-full bg-surface-850 text-emerald-400 font-bold border border-white/5">
                      {systemStats?.hardware?.os ? `${systemStats.hardware.os} Host` : 'Live System'}
                    </span>
                  </div>
                  <RamDonutChart ram={systemStats?.ram} onRefresh={fetchStats} />
                </div>
              </div>

              {/* Recent Video Projects Table */}
              <div className="glass-card rounded-2xl p-6 border border-white/10">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-bold text-base text-white">Recent Video Projects</h3>
                    <p className="text-xs text-slate-400">Latest active and converted video projects</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveTab("videos")}
                    className="text-xs text-brand-400 hover:text-brand-300 font-bold"
                  >
                    View All Videos →
                  </button>
                </div>

                {videosList.length === 0 ? (
                  <div className="text-center py-8 text-slate-500 text-xs">
                    No videos created yet. Click "+ Add New Video" to begin.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400 uppercase tracking-wider font-semibold">
                          <th className="pb-3 pl-2">Title</th>
                          <th className="pb-3">YouTube Link</th>
                          <th className="pb-3">Languages</th>
                          <th className="pb-3">Conversions</th>
                          <th className="pb-3 text-right pr-2">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {videosList.slice(0, 5).map(v => (
                          <tr key={v.id} className="hover:bg-surface-850 transition">
                            <td className="py-3 pl-2 font-bold text-slate-200">
                              {v.title}
                            </td>
                            <td className="py-3">
                              {v.youtube_url ? (
                                <a
                                  href={v.youtube_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-brand-400 hover:text-brand-300 font-medium inline-flex items-center gap-1"
                                >
                                  <span className="truncate max-w-[200px]">{v.youtube_url}</span>
                                  <ExternalLink className="w-3.5 h-3.5" />
                                </a>
                              ) : (
                                <span className="text-slate-500">Local Upload</span>
                              )}
                            </td>
                            <td className="py-3">
                              <div className="flex items-center gap-1">
                                {(v.languages || []).map(code => (
                                  <span
                                    key={code}
                                    className="px-2 py-0.5 rounded bg-surface-800 text-slate-300 font-semibold border border-white/5 text-[11px]"
                                  >
                                    {LANG_MAP[code]?.flag} {code.toUpperCase()}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="py-3 text-slate-400">
                              {v.conversions?.length || 0} part(s)
                            </td>
                            <td className="py-3 text-right pr-2">
                              <div className="flex items-center justify-end gap-2">
                                <button
                                  type="button"
                                  onClick={() => handleOpenVideoDetails(v.id)}
                                  className="px-3 py-1 rounded-lg bg-surface-800 hover:bg-brand-600 text-slate-200 hover:text-white font-semibold transition"
                                >
                                  Details
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleDeleteVideo(v.id, v.title)}
                                  className="p-1 rounded-lg bg-surface-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-white/5 transition"
                                  title="Delete Video"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "videos" && (
            <div className="space-y-6">
              <div className="glass-card rounded-2xl overflow-hidden border border-white/10">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 bg-surface-900/50 text-slate-400 uppercase font-semibold">
                      <th className="py-3.5 pl-6">Title & ID</th>
                      <th className="py-3.5">YouTube Link</th>
                      <th className="py-3.5">Languages</th>
                      <th className="py-3.5">Parts</th>
                      <th className="py-3.5 text-right pr-6">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {videosList.map(video => (
                      <tr key={video.id} className="hover:bg-surface-850 transition">
                        <td className="py-4 pl-6 font-bold text-slate-100">{video.title}</td>
                        <td className="py-4">
                          <a
                            href={video.youtube_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-brand-400 hover:underline inline-flex items-center gap-1"
                          >
                            <span className="truncate max-w-[200px]">{video.youtube_url}</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </td>
                        <td className="py-4">
                          <div className="flex gap-1">
                            {(video.languages || []).map(code => (
                              <span key={code} className="px-2 py-0.5 rounded bg-surface-800 text-slate-300 font-semibold">
                                {LANG_MAP[code]?.flag} {code.toUpperCase()}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-4">{video.conversions?.length || 0} part(s)</td>
                        <td className="py-4 text-right pr-6">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleOpenVideoDetails(video.id)}
                              className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs transition"
                            >
                              Details
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeleteVideo(video.id, video.title)}
                              className="p-1.5 rounded-lg bg-surface-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-white/5 transition"
                              title="Delete Video Project"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === "video_details" && selectedVideoId && (() => {
            const selectedVideo = videosList.find(v => v.id === selectedVideoId);
            const conversions = selectedVideo?.conversions || [];

            return (
              <div className="space-y-6">
                {/* Header */}
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
                  <div>
                    <button
                      type="button"
                      onClick={() => setActiveTab("videos")}
                      className="text-xs text-slate-400 hover:text-white flex items-center gap-1 font-semibold mb-2 transition"
                    >
                      <ArrowLeft className="w-4 h-4" />
                      <span>Back to Videos List</span>
                    </button>
                    <h2 className="text-2xl font-black text-white">
                      {selectedVideo?.title || `Video ID: ${selectedVideoId}`}
                    </h2>
                    <div className="flex flex-wrap items-center gap-3 mt-1.5 text-xs">
                      <span className="font-mono text-slate-400 bg-surface-900 px-2 py-0.5 rounded border border-white/5">
                        ID: {selectedVideoId}
                      </span>
                      {selectedVideo?.youtube_url && (
                        <a
                          href={selectedVideo.youtube_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-brand-400 hover:text-brand-300 font-semibold inline-flex items-center gap-1"
                        >
                          <span>View on YouTube</span>
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                      <div className="flex items-center gap-1">
                        {(selectedVideo?.languages || []).map(code => (
                          <span
                            key={code}
                            className="px-2 py-0.5 rounded bg-surface-850 text-slate-300 font-bold border border-white/5 text-[11px]"
                          >
                            {LANG_MAP[code]?.flag} {code.toUpperCase()}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Delete Video Option inside details */}
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => handleDeleteVideo(selectedVideoId, selectedVideo?.title)}
                      className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 border border-red-500/30 font-bold text-xs transition shadow-sm"
                      title="Delete this entire video project"
                    >
                      <Trash2 className="w-4 h-4" />
                      <span>Delete Video</span>
                    </button>
                  </div>
                </div>

                {/* Converted Videos & Parts Section */}
                <div className="glass-card rounded-2xl p-6 border border-white/10">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="font-bold text-lg text-white">
                        Converted Videos & Parts ({conversions.length})
                      </h3>
                      <p className="text-xs text-slate-400">
                        All conversions created for this video project.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={fetchVideos}
                      className="p-2 rounded-lg bg-surface-850 hover:bg-surface-700 text-slate-300 transition"
                      title="Reload conversions"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                  </div>

                  {conversions.length === 0 ? (
                    <div className="text-center py-12 text-slate-500 text-xs">
                      No converted parts recorded yet for this video.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {conversions.map((conv, idx) => (
                        <div key={conv.job_id || idx} className="rounded-xl p-5 bg-surface-900 border border-white/5 space-y-4">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-sm text-white">{conv.part_name || "Full Video"}</span>
                              <span className="text-[10px] text-slate-400 font-mono">Job: {conv.job_id}</span>
                            </div>
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 uppercase">
                              {conv.status || "Completed"}
                            </span>
                          </div>

                          {/* Language badges */}
                          <div className="flex items-center gap-1.5">
                            {(conv.languages || []).map(l => (
                              <span key={l} className="text-xs px-2 py-0.5 rounded bg-surface-800 text-slate-200 border border-white/5 font-semibold">
                                {LANG_MAP[l]?.flag} {LANG_MAP[l]?.name || l.toUpperCase()}
                              </span>
                            ))}
                          </div>

                          {/* Video Player */}
                          {conv.output_video_url ? (
                            <div className="rounded-xl overflow-hidden bg-black border border-white/10 aspect-video">
                              <video
                                controls
                                className="w-full h-full object-contain"
                                src={conv.output_video_url}
                                preload="metadata"
                              />
                            </div>
                          ) : (
                            <div className="aspect-video bg-surface-950 rounded-xl flex items-center justify-center text-xs text-slate-500">
                              Video rendering in background...
                            </div>
                          )}

                          {/* Action buttons including Delete */}
                          <div className="flex flex-wrap items-center gap-2 pt-2">
                            {conv.output_video_url && (
                              <a
                                href={conv.output_video_url}
                                download
                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-800 hover:bg-surface-700 text-slate-200 text-xs font-semibold transition"
                              >
                                <Download className="w-3.5 h-3.5" />
                                <span>Download MP4</span>
                              </a>
                            )}
                            {conv.zip_url && (
                              <a
                                href={conv.zip_url}
                                download
                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-800 hover:bg-surface-700 text-slate-200 text-xs font-semibold transition"
                              >
                                <Download className="w-3.5 h-3.5" />
                                <span>ZIP Pack</span>
                              </a>
                            )}
                            <button
                              type="button"
                              onClick={() => handleDeleteConversion(conv.job_id, conv.part_name)}
                              className="p-1.5 rounded-lg bg-surface-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-white/5 transition ml-auto"
                              title="Delete this converted video"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
          {activeTab === "ytd" && (
            <YtdChannelsView
              channels={ytdChannels}
              stats={ytdStats}
              isLoading={isLoadingYtd}
              onRefresh={() => { fetchYtdChannels(); fetchYtdStats(); }}
              onOpenAddModal={() => setIsAddChannelModalOpen(true)}
              onOpenDetails={(chId) => { setSelectedChannelId(chId); setActiveTab("ytd_channel_details"); }}
              onEditChannel={(ch) => setEditingChannel(ch)}
              onDeleteChannel={handleDeleteChannel}
              onSyncChannel={handleSyncChannel}
            />
          )}

          {activeTab === "ytd_channel_details" && selectedChannelId && (
            <YtdChannelDetailsView
              channelId={selectedChannelId}
              onBack={() => { setActiveTab("ytd"); setSelectedChannelId(null); fetchYtdChannels(); }}
              onDownloadVideo={(video) => setDownloadModalVideo(video)}
              onDeleteVideo={handleDeleteYtdVideo}
              onSyncChannel={handleSyncChannel}
            />
          )}
        </div>
      </main>

      {/* Add Video Modal */}
      {isAddVideoModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="glass-card rounded-2xl p-6 w-full max-w-lg border border-white/10 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Add New Video Project</h3>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const title = e.target.title.value;
                const yt = e.target.youtube_url.value;
                const res = await fetch("/api/videos", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ title, youtube_url: yt })
                });
                if (res.ok) {
                  const created = await res.json();
                  setIsAddVideoModalOpen(false);
                  fetchVideos();
                  setSelectedVideoId(created.id);
                  setActiveTab("video_details");
                }
              }}
              className="space-y-4"
            >
              <div>
                <label className="block text-xs font-bold uppercase text-slate-300 mb-1">YouTube Link</label>
                <input
                  name="youtube_url"
                  required
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="w-full px-4 py-2.5 rounded-xl bg-surface-900 border border-slate-700 text-sm text-slate-100 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-300 mb-1">Title</label>
                <input
                  name="title"
                  required
                  placeholder="Solo Leveling Recap Episode 1"
                  className="w-full px-4 py-2.5 rounded-xl bg-surface-900 border border-slate-700 text-sm text-slate-100 outline-none"
                />
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsAddVideoModalOpen(false)}
                  className="px-4 py-2 text-xs font-bold text-slate-400"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2.5 rounded-xl bg-brand-600 text-white text-xs font-bold"
                >
                  Create & Open
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Channel Modal */}
      {isAddChannelModalOpen && (
        <AddChannelModal
          onClose={() => setIsAddChannelModalOpen(false)}
          onCreated={(newCh) => {
            setIsAddChannelModalOpen(false);
            fetchYtdChannels();
            fetchYtdStats();
          }}
        />
      )}

      {/* Edit Channel Modal */}
      {editingChannel && (
        <EditChannelModal
          channel={editingChannel}
          onClose={() => setEditingChannel(null)}
          onUpdated={() => {
            setEditingChannel(null);
            fetchYtdChannels();
          }}
        />
      )}

      {/* Download Video Modal (Full, Splits, Shorts) */}
      {downloadModalVideo && (
        <YtdDownloadModal
          video={downloadModalVideo}
          onClose={() => setDownloadModalVideo(null)}
          onDownloadStarted={() => {
            fetchYtdStats();
          }}
        />
      )}
    </div>
  );
}

// =========================================================================
// YTD Helper Functions
// =========================================================================
function formatYtdDuration(seconds) {
  if (!seconds || seconds <= 0) return "--:--";
  const secNum = parseInt(seconds, 10);
  const hours = Math.floor(secNum / 3600);
  const minutes = Math.floor((secNum % 3600) / 60);
  const secs = secNum % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// =========================================================================
// YTD Channels View Component
// =========================================================================
function YtdChannelsView({
  channels,
  stats,
  isLoading,
  onRefresh,
  onOpenAddModal,
  onOpenDetails,
  onEditChannel,
  onDeleteChannel,
  onSyncChannel
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [syncingId, setSyncingId] = useState(null);

  const handleSync = async (id) => {
    setSyncingId(id);
    await onSyncChannel(id);
    setSyncingId(null);
  };

  const filteredChannels = (channels || []).filter(c => {
    const query = searchTerm.toLowerCase();
    return (c.title || "").toLowerCase().includes(query) || (c.url || "").toLowerCase().includes(query);
  });

  return (
    <div className="space-y-8">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl glass-card border border-white/5 bg-gradient-to-r from-surface-900 via-surface-850 to-red-950/20">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="p-1.5 rounded-lg bg-red-600/20 text-red-400 border border-red-500/30">
              <Youtube className="w-4 h-4" />
            </span>
            <span className="text-xs font-bold text-red-400 uppercase tracking-widest">
              YouTube Downloader (YTD)
            </span>
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight">Connected Channels</h2>
          <p className="text-xs text-slate-400 mt-1 max-w-xl">
            Track YouTube channels, sync published videos, download full MP4 files, slice long videos into 2/5/9 min series, or render vertical shorts.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onRefresh}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-200 text-xs font-semibold transition border border-white/10"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={onOpenAddModal}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white text-xs font-bold shadow-lg shadow-red-500/25 transition"
          >
            <Plus className="w-4 h-4" />
            <span>Add Channel</span>
          </button>
        </div>
      </div>

      {/* Quick Metrics Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl glass-panel border border-white/5">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Channels</span>
          <div className="text-2xl font-black text-white mt-1">{channels.length}</div>
        </div>
        <div className="p-4 rounded-xl glass-panel border border-white/5">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Total Videos</span>
          <div className="text-2xl font-black text-brand-400 mt-1">{stats?.total_videos || 0}</div>
        </div>
        <div className="p-4 rounded-xl glass-panel border border-white/5">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Downloaded</span>
          <div className="text-2xl font-black text-emerald-400 mt-1">{stats?.downloaded_videos || 0}</div>
        </div>
        <div className="p-4 rounded-xl glass-panel border border-white/5">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Shorts Generated</span>
          <div className="text-2xl font-black text-purple-400 mt-1">{stats?.shorts_count || 0}</div>
        </div>
      </div>

      {/* Search Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <input
            type="text"
            placeholder="Search channels by title or URL..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-4 py-2.5 rounded-xl bg-surface-900 border border-slate-700/80 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-red-500"
          />
        </div>
        <span className="text-xs text-slate-500 font-medium">
          Showing {filteredChannels.length} of {channels.length} channels
        </span>
      </div>

      {/* Channels Grid / List */}
      {isLoading && channels.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-16 text-slate-400">
          <div className="w-8 h-8 border-2 border-red-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          <p className="text-xs">Loading channels...</p>
        </div>
      ) : filteredChannels.length === 0 ? (
        <div className="p-16 rounded-2xl glass-card border border-white/5 text-center flex flex-col items-center justify-center">
          <div className="w-14 h-14 rounded-2xl bg-red-600/10 text-red-400 flex items-center justify-center mb-4">
            <Youtube className="w-8 h-8" />
          </div>
          <h3 className="text-base font-bold text-white mb-1">
            {searchTerm ? "No matching channels" : "No YouTube channels added yet"}
          </h3>
          <p className="text-xs text-slate-400 max-w-sm mb-6">
            {searchTerm ? "Try adjusting your search query." : "Add a YouTube channel URL or @handle to start tracking and downloading videos."}
          </p>
          {!searchTerm && (
            <button
              type="button"
              onClick={onOpenAddModal}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold transition shadow-lg shadow-red-500/20"
            >
              <Plus className="w-4 h-4" />
              <span>Add First Channel</span>
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredChannels.map((ch) => (
            <div
              key={ch.id}
              className="p-5 rounded-2xl glass-card border border-white/5 hover:border-red-500/30 flex flex-col justify-between transition-all duration-300 group shadow-lg"
            >
              <div>
                {/* Channel Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-600 to-rose-700 flex items-center justify-center text-white font-black text-sm flex-shrink-0 shadow-md shadow-red-600/30">
                      <Youtube className="w-5 h-5" />
                    </div>
                    <div className="overflow-hidden">
                      <h4 className="font-bold text-white text-sm truncate group-hover:text-red-400 transition">
                        {ch.title || "Untitled Channel"}
                      </h4>
                      <a
                        href={ch.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[11px] text-red-400 hover:text-red-300 truncate font-mono mt-0.5"
                      >
                        <span className="truncate">{ch.url}</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0" />
                      </a>
                    </div>
                  </div>
                </div>

                {/* Channel Stats Row */}
                <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-white/5 text-xs">
                  <div className="p-2 rounded-lg bg-surface-900 border border-white/5">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Videos</span>
                    <div className="font-bold text-slate-200 mt-0.5">{ch.video_count || 0}</div>
                  </div>
                  <div className="p-2 rounded-lg bg-surface-900 border border-white/5">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Downloaded</span>
                    <div className="font-bold text-emerald-400 mt-0.5">{ch.downloaded_count || 0}</div>
                  </div>
                </div>

                <div className="mt-3 text-[10px] text-slate-500 flex items-center justify-between">
                  <span>Last Synced:</span>
                  <span className="font-medium text-slate-400">
                    {ch.last_synced_at ? new Date(ch.last_synced_at).toLocaleString() : "Never"}
                  </span>
                </div>
              </div>

              {/* Actions Bar */}
              <div className="flex items-center gap-2 mt-5 pt-3 border-t border-white/5">
                <button
                  type="button"
                  onClick={() => onOpenDetails(ch.id)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition shadow-sm shadow-brand-500/20"
                >
                  <Info className="w-3.5 h-3.5" />
                  <span>Details</span>
                </button>

                <button
                  type="button"
                  title="Sync all channel videos"
                  disabled={syncingId === ch.id}
                  onClick={() => handleSync(ch.id)}
                  className={`p-2 rounded-xl border border-white/10 transition ${syncingId === ch.id ? 'bg-red-500/20 text-red-300 animate-spin' : 'bg-surface-800 hover:bg-surface-700 text-slate-300 hover:text-white'}`}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>

                <button
                  type="button"
                  title="Edit channel details"
                  onClick={() => onEditChannel(ch)}
                  className="p-2 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-300 hover:text-white border border-white/10 transition"
                >
                  <Edit2 className="w-3.5 h-3.5" />
                </button>

                <button
                  type="button"
                  title="Delete channel"
                  onClick={() => onDeleteChannel(ch.id, ch.title)}
                  className="p-2 rounded-xl bg-surface-800 hover:bg-red-500/20 text-slate-300 hover:text-red-400 border border-white/10 transition"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// YTD Channel Details View Component
// =========================================================================
function YtdChannelDetailsView({
  channelId,
  onBack,
  onDownloadVideo,
  onDeleteVideo,
  onSyncChannel
}) {
  const [channel, setChannel] = useState(null);
  const [videos, setVideos] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const loadChannelAndVideos = async () => {
    try {
      const [chRes, vidsRes] = await Promise.all([
        fetch(`/api/ytd/channels/${channelId}`),
        fetch(`/api/ytd/channels/${channelId}/videos?limit=250`)
      ]);
      if (chRes.ok) {
        setChannel(await chRes.json());
      }
      if (vidsRes.ok) {
        const vidsData = await vidsRes.json();
        setVideos(Array.isArray(vidsData) ? vidsData : (vidsData.videos || []));
      }
    } catch (err) {
      console.error("Failed to load channel videos:", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadChannelAndVideos();
  }, [channelId]);

  // Polling for active background downloads
  useEffect(() => {
    const hasActive = (videos || []).some(v => ['queued', 'downloading', 'splitting', 'generating_shorts'].includes(v.download_status));
    if (!hasActive) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/ytd/channels/${channelId}/videos?limit=250`);
        if (res.ok) {
          const fresh = await res.json();
          setVideos(Array.isArray(fresh) ? fresh : (fresh.videos || []));
        }
      } catch (e) {
        console.error("Polling error:", e);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [channelId, videos]);

  const handleManualSync = async () => {
    setIsSyncing(true);
    try {
      await onSyncChannel(channelId);
      await loadChannelAndVideos();
    } finally {
      setIsSyncing(false);
    }
  };

  const handleDelete = async (vid) => {
    const success = await onDeleteVideo(vid.id, vid.title);
    if (success) {
      setVideos(prev => prev.filter(v => v.id !== vid.id));
    }
  };

  const filteredVideos = (videos || []).filter(v => {
    const matchesSearch =
      (v.title || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (v.youtube_id || "").toLowerCase().includes(searchQuery.toLowerCase());

    if (!matchesSearch) return false;
    if (statusFilter === "downloaded") return Boolean(v.is_downloaded);
    if (statusFilter === "not_downloaded") return !v.is_downloaded;
    return true;
  });

  const downloadedCount = (videos || []).filter(v => Boolean(v.is_downloaded)).length;

  return (
    <div className="space-y-6">
      {/* Top Bar Navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-surface-900 hover:bg-surface-850 text-slate-300 hover:text-white border border-white/5 text-xs font-semibold transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to All Channels</span>
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleManualSync}
            disabled={isSyncing}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold transition shadow-lg shadow-red-500/25 ${isSyncing ? 'opacity-70 cursor-not-allowed' : ''}`}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? "animate-spin" : ""}`} />
            <span>{isSyncing ? "Syncing Videos..." : "Sync Channel Now"}</span>
          </button>
        </div>
      </div>

      {/* Channel Banner Card */}
      <div className="p-6 rounded-2xl glass-card border border-white/5 bg-gradient-to-r from-surface-900 via-surface-850 to-red-950/20 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-center gap-4 overflow-hidden">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-red-600 to-rose-600 flex items-center justify-center text-white text-xl font-black shadow-lg shadow-red-600/30 flex-shrink-0">
            <Youtube className="w-7 h-7" />
          </div>
          <div className="overflow-hidden">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 uppercase tracking-widest">
                Tracked Channel
              </span>
              {channel?.last_synced_at && (
                <span className="text-[10px] text-slate-500">
                  Synced {new Date(channel.last_synced_at).toLocaleTimeString()}
                </span>
              )}
            </div>
            <h2 className="text-xl font-black text-white truncate mt-1">
              {channel?.title || "Channel Videos"}
            </h2>
            {channel?.url && (
              <a
                href={channel.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 font-mono mt-0.5 truncate"
              >
                <span className="truncate">{channel.url}</span>
                <ExternalLink className="w-3 h-3 flex-shrink-0" />
              </a>
            )}
          </div>
        </div>

        {/* Quick Metrics */}
        <div className="flex items-center gap-3">
          <div className="px-4 py-2.5 rounded-xl bg-surface-900 border border-white/5 text-center">
            <div className="text-[10px] font-bold text-slate-400 uppercase">Total Videos</div>
            <div className="text-lg font-black text-white mt-0.5">{videos.length}</div>
          </div>
          <div className="px-4 py-2.5 rounded-xl bg-surface-900 border border-white/5 text-center">
            <div className="text-[10px] font-bold text-slate-400 uppercase">Downloaded</div>
            <div className="text-lg font-black text-emerald-400 mt-0.5">{downloadedCount}</div>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            placeholder="Search videos by title or ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-4 py-2 rounded-xl bg-surface-900 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-red-500"
          />
        </div>

        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-surface-900 border border-white/5 text-xs self-stretch sm:self-auto">
          <button
            type="button"
            onClick={() => setStatusFilter("all")}
            className={`px-3 py-1.5 rounded-lg font-semibold transition ${statusFilter === 'all' ? 'bg-red-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}
          >
            All ({videos.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("downloaded")}
            className={`px-3 py-1.5 rounded-lg font-semibold transition ${statusFilter === 'downloaded' ? 'bg-emerald-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}
          >
            Downloaded ({downloadedCount})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("not_downloaded")}
            className={`px-3 py-1.5 rounded-lg font-semibold transition ${statusFilter === 'not_downloaded' ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-white'}`}
          >
            Not Downloaded ({videos.length - downloadedCount})
          </button>
        </div>
      </div>

      {/* Video List */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center p-16 text-slate-400">
          <div className="w-8 h-8 border-2 border-red-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          <p className="text-xs">Loading channel videos...</p>
        </div>
      ) : filteredVideos.length === 0 ? (
        <div className="p-16 rounded-2xl glass-card border border-white/5 text-center flex flex-col items-center justify-center">
          <div className="w-12 h-12 rounded-2xl bg-red-600/10 text-red-400 flex items-center justify-center mb-3">
            <Youtube className="w-6 h-6" />
          </div>
          <h3 className="text-sm font-bold text-white mb-1">No videos found</h3>
          <p className="text-xs text-slate-400 max-w-sm mb-4">
            {searchQuery ? "No videos match your search query." : "No videos have been synced for this channel yet."}
          </p>
          {!searchQuery && (
            <button
              type="button"
              onClick={handleManualSync}
              className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold transition"
            >
              Sync Videos Now
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredVideos.map((vid) => {
            const isProcessing = ['queued', 'downloading', 'splitting', 'generating_shorts'].includes(vid.download_status);

            return (
              <div
                key={vid.id}
                className="p-4 rounded-xl glass-card border border-white/5 hover:border-slate-700 flex flex-col lg:flex-row lg:items-center justify-between gap-4 transition group"
              >
                {/* Video Info Left */}
                <div className="flex items-start gap-4 overflow-hidden flex-1">
                  <div className="relative w-28 h-16 rounded-lg bg-surface-900 border border-white/10 flex-shrink-0 overflow-hidden group-hover:border-red-500/40 transition">
                    {vid.thumbnail ? (
                      <img src={vid.thumbnail} alt={vid.title} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-red-500 bg-surface-850">
                        <Youtube className="w-6 h-6" />
                      </div>
                    )}
                    {vid.duration_seconds > 0 && (
                      <span className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/80 text-[10px] font-mono text-white">
                        {formatYtdDuration(vid.duration_seconds)}
                      </span>
                    )}
                  </div>

                  <div className="overflow-hidden flex-1">
                    <h4 className="font-bold text-white text-sm line-clamp-1 group-hover:text-red-400 transition" title={vid.title}>
                      {vid.title}
                    </h4>
                    <div className="flex flex-wrap items-center gap-2 mt-1">
                      <a
                        href={vid.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] text-red-400 hover:text-red-300 font-mono"
                      >
                        <span>Watch on YouTube</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                      {vid.published_at && (
                        <span className="text-[10px] text-slate-500">
                          • {vid.published_at.substring(0, 10)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Middle: Download Status Badge */}
                <div className="flex items-center gap-3 lg:px-4">
                  {isProcessing ? (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs font-semibold">
                      <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping"></span>
                      <span className="capitalize">{vid.download_status.replace('_', ' ')}...</span>
                    </div>
                  ) : vid.is_downloaded ? (
                    <div className="flex flex-col items-start lg:items-end">
                      <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold flex items-center gap-1">
                        <span>✓</span>
                        <span>Downloaded</span>
                      </span>
                      <span className="text-[10px] text-slate-400 mt-0.5 uppercase tracking-wider font-semibold">
                        {vid.download_type === 'splits' ? 'Splits (ZIP)' : vid.download_type === 'shorts' ? 'Shorts (ZIP)' : 'Full MP4'}
                        {vid.file_size_mb ? ` • ${vid.file_size_mb} MB` : ''}
                      </span>
                    </div>
                  ) : (
                    <span className="px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 border border-white/5 text-xs font-medium">
                      Not Downloaded
                    </span>
                  )}
                </div>

                {/* Right: Actions */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    type="button"
                    disabled={isProcessing}
                    onClick={() => onDownloadVideo(vid)}
                    className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold transition shadow-sm ${vid.is_downloaded ? 'bg-surface-800 hover:bg-surface-700 text-slate-200 border border-white/10' : 'bg-red-600 hover:bg-red-500 text-white shadow-red-500/20'}`}
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>{vid.is_downloaded ? "Re-download" : "Download"}</span>
                  </button>

                  {Boolean(vid.is_downloaded) && (
                    <a
                      href={`/api/ytd/videos/${vid.id}/file`}
                      download
                      title="Save downloaded file to computer"
                      className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 text-xs font-semibold transition"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Save File</span>
                    </a>
                  )}

                  <button
                    type="button"
                    title="Delete video & blacklist from sync"
                    onClick={() => handleDelete(vid)}
                    className="p-2 rounded-xl bg-surface-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-white/10 transition"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// Add Channel Modal Component
// =========================================================================
function AddChannelModal({ onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [autoSync, setAutoSync] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!url.trim()) {
      setError("Please provide a YouTube channel URL or @handle.");
      return;
    }
    setIsLoading(true);
    setError("");

    try {
      const res = await fetch("/api/ytd/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          title: title.trim(),
          auto_sync: autoSync
        })
      });

      if (res.ok) {
        const data = await res.json();
        onCreated(data);
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.detail || "Failed to add channel.");
      }
    } catch (err) {
      setError(err.message || "Network error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-lg p-6 rounded-2xl glass-card border border-white/10 bg-surface-900 shadow-2xl">
        <div className="flex items-center justify-between pb-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-xl bg-red-600/20 text-red-400 border border-red-500/30">
              <Youtube className="w-5 h-5" />
            </span>
            <div>
              <h3 className="text-base font-black text-white">Add YouTube Channel</h3>
              <p className="text-xs text-slate-400">Track and download videos from a channel</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-surface-800 transition"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
              Channel URL or @Handle <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="https://www.youtube.com/@veritasium or @veritasium"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-surface-850 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-red-500"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Supports custom handles (@channel), channel URLs, or user URLs.
            </p>
          </div>

          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
              Channel Title (Optional)
            </label>
            <input
              type="text"
              placeholder="e.g. Veritasium (leave blank to auto-detect)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-surface-850 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-red-500"
            />
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoSync}
                onChange={(e) => setAutoSync(e.target.checked)}
                className="w-4 h-4 rounded text-red-600 bg-surface-850 border-slate-700 focus:ring-red-500"
              />
              <span className="text-xs text-slate-300 font-medium">
                Automatically sync videos immediately after adding
              </span>
            </label>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-300 text-xs font-semibold transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className={`flex items-center gap-2 px-5 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold transition shadow-lg shadow-red-500/25 ${isLoading ? 'opacity-70 cursor-not-allowed' : ''}`}
            >
              {isLoading && <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></span>}
              <span>{isLoading ? "Adding Channel..." : "Add Channel"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// =========================================================================
// Edit Channel Modal Component
// =========================================================================
function EditChannelModal({ channel, onClose, onUpdated }) {
  const [title, setTitle] = useState(channel?.title || "");
  const [url, setUrl] = useState(channel?.url || "");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError("");

    try {
      const res = await fetch(`/api/ytd/channels/${channel.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          url: url.trim()
        })
      });

      if (res.ok) {
        onUpdated();
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.detail || "Failed to update channel.");
      }
    } catch (err) {
      setError(err.message || "Network error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-lg p-6 rounded-2xl glass-card border border-white/10 bg-surface-900 shadow-2xl">
        <div className="flex items-center justify-between pb-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-xl bg-brand-600/20 text-brand-400 border border-brand-500/30">
              <Edit2 className="w-4 h-4" />
            </span>
            <div>
              <h3 className="text-base font-black text-white">Edit Channel Details</h3>
              <p className="text-xs text-slate-400">Update channel title or URL</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-surface-800 transition"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
              Channel Title
            </label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-surface-850 border border-slate-700 text-xs text-white focus:outline-none focus:border-brand-500"
            />
          </div>

          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-1.5">
              Channel URL
            </label>
            <input
              type="text"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-surface-850 border border-slate-700 text-xs text-white focus:outline-none focus:border-brand-500"
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-300 text-xs font-semibold transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className={`flex items-center gap-2 px-5 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold transition ${isLoading ? 'opacity-70 cursor-not-allowed' : ''}`}
            >
              {isLoading && <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></span>}
              <span>{isLoading ? "Saving..." : "Save Changes"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// =========================================================================
// YTD Video Download Modal (Full, Splits, Shorts)
// =========================================================================
function YtdDownloadModal({ video, onClose, onDownloadStarted }) {
  const [downloadType, setDownloadType] = useState("full");
  const [partDurationMins, setPartDurationMins] = useState(5);
  const [numShorts, setNumShorts] = useState(3);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const handleStartDownload = async () => {
    setIsLoading(true);
    setError("");

    try {
      const res = await fetch(`/api/ytd/videos/${video.id}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          download_type: downloadType,
          part_duration_mins: partDurationMins,
          num_shorts: numShorts
        })
      });

      if (res.ok) {
        onDownloadStarted();
        onClose();
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.detail || "Failed to start download.");
      }
    } catch (err) {
      setError(err.message || "Network error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm">
      <div className="w-full max-w-xl p-6 rounded-2xl glass-card border border-white/10 bg-surface-900 shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between pb-4 border-b border-white/5">
          <div className="flex items-center gap-2.5">
            <span className="p-2 rounded-xl bg-red-600/20 text-red-400 border border-red-500/30">
              <Download className="w-5 h-5" />
            </span>
            <div>
              <h3 className="text-base font-black text-white">Download Video Options</h3>
              <p className="text-xs text-slate-400">Choose output format, splits, or vertical shorts</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-surface-800 transition"
          >
            ✕
          </button>
        </div>

        {/* Video Preview Card */}
        <div className="mt-4 p-3.5 rounded-xl bg-surface-850 border border-white/5 flex items-center gap-3">
          <div className="w-16 h-10 rounded-lg bg-surface-900 overflow-hidden flex-shrink-0 flex items-center justify-center text-red-400">
            {video.thumbnail ? (
              <img src={video.thumbnail} alt={video.title} className="w-full h-full object-cover" />
            ) : (
              <Youtube className="w-6 h-6" />
            )}
          </div>
          <div className="overflow-hidden flex-1">
            <h4 className="text-xs font-bold text-white truncate">{video.title}</h4>
            <div className="flex items-center gap-2 text-[10px] text-slate-400 mt-0.5">
              <span>Duration: {formatYtdDuration(video.duration_seconds)}</span>
              <span>•</span>
              <span>ID: {video.youtube_id}</span>
            </div>
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Download Option Selectors */}
        <div className="mt-5 space-y-3">
          {/* Option 1: Full Video */}
          <div
            onClick={() => setDownloadType("full")}
            className={`p-4 rounded-xl border cursor-pointer transition flex items-start gap-3.5 ${downloadType === 'full' ? 'bg-red-500/10 border-red-500 shadow-md shadow-red-500/10' : 'bg-surface-850 border-white/5 hover:border-slate-700'}`}
          >
            <div className={`w-4 h-4 rounded-full mt-0.5 border flex items-center justify-center ${downloadType === 'full' ? 'border-red-500 bg-red-500' : 'border-slate-500'}`}>
              {downloadType === 'full' && <div className="w-1.5 h-1.5 rounded-full bg-white"></div>}
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-white">Full Video (Original MP4)</span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-surface-900 text-slate-300 border border-white/5 uppercase">
                  Single MP4
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Downloads the complete original high-resolution YouTube video with full audio track intact.
              </p>
            </div>
          </div>

          {/* Option 2: Splits */}
          <div
            onClick={() => setDownloadType("splits")}
            className={`p-4 rounded-xl border cursor-pointer transition flex items-start gap-3.5 ${downloadType === 'splits' ? 'bg-red-500/10 border-red-500 shadow-md shadow-red-500/10' : 'bg-surface-850 border-white/5 hover:border-slate-700'}`}
          >
            <div className={`w-4 h-4 rounded-full mt-0.5 border flex items-center justify-center ${downloadType === 'splits' ? 'border-red-500 bg-red-500' : 'border-slate-500'}`}>
              {downloadType === 'splits' && <div className="w-1.5 h-1.5 rounded-full bg-white"></div>}
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Scissors className="w-4 h-4" />
                  <span className="text-sm font-bold text-white">Splits (Multi-Part Video Series)</span>
                </div>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-surface-900 text-slate-300 border border-white/5 uppercase">
                  ZIP Archive
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Splits the video into equal-length parts packaged into a ZIP archive for serial multi-part posts.
              </p>

              {downloadType === "splits" && (
                <div className="mt-3 pt-3 border-t border-white/10" onClick={(e) => e.stopPropagation()}>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-300 mb-2">
                    Select Split Duration:
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {[2, 5, 9].map((mins) => (
                      <button
                        key={mins}
                        type="button"
                        onClick={() => setPartDurationMins(mins)}
                        className={`py-2 px-3 rounded-lg text-xs font-bold transition border ${partDurationMins === mins ? 'bg-red-600 text-white border-red-500 shadow-sm' : 'bg-surface-900 text-slate-300 border-white/5 hover:bg-surface-800'}`}
                      >
                        {mins} mins
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Option 3: Shorts */}
          <div
            onClick={() => setDownloadType("shorts")}
            className={`p-4 rounded-xl border cursor-pointer transition flex items-start gap-3.5 ${downloadType === 'shorts' ? 'bg-red-500/10 border-red-500 shadow-md shadow-red-500/10' : 'bg-surface-850 border-white/5 hover:border-slate-700'}`}
          >
            <div className={`w-4 h-4 rounded-full mt-0.5 border flex items-center justify-center ${downloadType === 'shorts' ? 'border-red-500 bg-red-500' : 'border-slate-500'}`}>
              {downloadType === 'shorts' && <div className="w-1.5 h-1.5 rounded-full bg-white"></div>}
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-white">Shorts (AI Climax 9:16 Vertical)</span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-surface-900 text-slate-300 border border-white/5 uppercase">
                  Vertical Reels ZIP
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Detects top scene climaxes and renders vertical 9:16 shorts with ambient wings packaged in a ZIP.
              </p>

              {downloadType === "shorts" && (
                <div className="mt-3 pt-3 border-t border-white/10" onClick={(e) => e.stopPropagation()}>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-300 mb-2">
                    Number of Shorts to Generate:
                  </label>
                  <div className="flex items-center gap-2">
                    {[1, 2, 3, 5, 8].map((num) => (
                      <button
                        key={num}
                        type="button"
                        onClick={() => setNumShorts(num)}
                        className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition border ${numShorts === num ? 'bg-red-600 text-white border-red-500 shadow-sm' : 'bg-surface-900 text-slate-300 border-white/5 hover:bg-surface-800'}`}
                      >
                        {num}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer Buttons */}
        <div className="flex items-center justify-end gap-3 pt-5 mt-5 border-t border-white/5">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 rounded-xl bg-surface-800 hover:bg-surface-700 text-slate-300 text-xs font-semibold transition"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isLoading}
            onClick={handleStartDownload}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white text-xs font-bold shadow-lg shadow-red-500/25 transition ${isLoading ? 'opacity-70 cursor-not-allowed' : ''}`}
          >
            {isLoading && <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></span>}
            <Download className="w-4 h-4" />
            <span>{isLoading ? "Starting Process..." : "Start Download"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
