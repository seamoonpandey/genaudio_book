import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { getMe } from "./api";
import styles from "./App.module.css";
import { PlayerProvider } from "./player";
import { Account } from "./pages/Account";
import { Book } from "./pages/Book";
import { Landing } from "./pages/Landing";
import { Library } from "./pages/Library";
import { Login } from "./pages/Login";
import { Reader } from "./pages/Reader";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: getMe, staleTime: 60_000 });
}

export function toggleTheme() {
  const root = document.documentElement;
  const next = root.dataset.theme === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  localStorage.setItem("genaudi-theme", next);
}

function Shell() {
  const { data, isLoading } = useMe();
  const loc = useLocation();
  if (isLoading) return null;
  if (!data?.user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return (
    <PlayerProvider>
      <header className={styles.nav}>
        <div className={`container ${styles.navInner}`}>
          <Link to="/library" className={styles.wordmark}>genaudi</Link>
          <nav className={styles.links}>
            <NavLink to="/library" className={({ isActive }) => (isActive ? styles.active : "")}>
              Library
            </NavLink>
            <NavLink to="/account" className={({ isActive }) => (isActive ? styles.active : "")}>
              Account
            </NavLink>
            <button className="btn btn-quiet btn-sm" onClick={toggleTheme} aria-label="Toggle theme">
              ◐
            </button>
          </nav>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </PlayerProvider>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route element={<Shell />}>
        <Route path="/library" element={<Library />} />
        <Route path="/books/:bookId" element={<Book />} />
        <Route path="/books/:bookId/read/:idx" element={<Reader />} />
        <Route path="/account" element={<Account />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
