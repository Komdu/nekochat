import { StoreProvider, useStore } from "./store";
import { LoginPage } from "./ui/LoginPage";
import { ChatPage } from "./ui/ChatPage";
import { CallOverlay } from "./ui/CallOverlay";

function AppInner() {
  const { phase } = useStore();
  if (phase === "boot") {
    return (
      <div className="boot">
        <div className="boot-spinner" />
        <div className="boot-text">Загрузка…</div>
      </div>
    );
  }
  if (phase === "login") return <LoginPage />;
  return (
    <>
      <ChatPage />
      <CallOverlay />
    </>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <AppInner />
    </StoreProvider>
  );
}