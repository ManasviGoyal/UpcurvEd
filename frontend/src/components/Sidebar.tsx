import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/hooks/use-toast";
import {
  Plus,
  MessageSquare,
  Settings,
  LogOut,
  Sun,
  Moon,
  ChevronsLeft,
  Trash2,
  Search,
  X,
  Share2,
  Copy,
  Check,
  Home,
  UserX
} from "lucide-react";
import type { Chat, User, ColorTheme, Theme } from "@/types";

interface SidebarProps {
  user: User;
  chats: Chat[];
  activeChatId: string | number | null;
  setActiveChatId: (id: string | number) => void;
  handleNewChat: () => void;
  setView: (view: string) => void;
  onOpenSettings?: () => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  colorTheme: ColorTheme;
  setColorTheme: (theme: ColorTheme) => void;
  handleLogout: () => void;
  handleDeleteAccount: () => void;
  desktopLocal?: boolean;
  isSidebarCollapsed: boolean;
  setIsSidebarCollapsed: (collapsed: boolean) => void;
  handleRenameChat: (id: string | number, name: string) => void;
  handleDeleteChat: (id: string | number) => void;
  onShareChat?: (chatId: string | number) => Promise<{ shareable: boolean; share_token?: string }>;
  onToggleShare?: (chatId: string | number, shareable: boolean) => Promise<void>;
}

export const Sidebar = ({
  chats,
  activeChatId,
  setActiveChatId,
  handleNewChat,
  setView,
  onOpenSettings,
  theme,
  setTheme,
  colorTheme,
  setColorTheme,
  handleLogout,
  handleDeleteAccount,
  desktopLocal = false,
  isSidebarCollapsed,
  setIsSidebarCollapsed,
  handleRenameChat,
  handleDeleteChat,
  onShareChat,
  onToggleShare,
}: SidebarProps) => {
  const navigate = useNavigate();
  const getThemeGradient = (theme: ColorTheme) => {
    switch (theme) {
      case 'rose':
        // Softer rose blend to better match the rest of the UI
        return 'from-rose-500 via-rose-400 to-pink-400';
      case 'green':
        return 'from-emerald-500 via-teal-500 to-green-600';
      case 'orange':
        return 'from-amber-500 via-orange-500 to-rose-500';
      case 'blue':
      default:
        return 'from-sky-500 via-indigo-500 to-violet-600';
    }
  };
  const themes: { name: ColorTheme }[] = [
    { name: 'blue' },
    { name: 'rose' },
    { name: 'green' },
    { name: 'orange' },
  ];

  const [renamingId, setRenamingId] = useState<string | number | null>(null);
  const [newName, setNewName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedShareLink, setCopiedShareLink] = useState<string | null>(null);
  const { toast } = useToast();

  const startRename = (chat: Chat) => {
    setRenamingId(chat.id);
    setNewName(chat.name);
  };

  const submitRename = () => {
    if (newName.trim()) {
      handleRenameChat(renamingId!, newName.trim());
    }
    setRenamingId(null);
  };

  // No dropdown menu anymore; inline actions instead

  useEffect(() => {
    if (renamingId && inputRef.current) {
      inputRef.current.focus();
    }
  }, [renamingId]);

  // Filter chats based on search query
  const filteredChats = chats.filter(chat => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      chat.name.toLowerCase().includes(query) ||
      chat.messages?.some(msg => msg.content.toLowerCase().includes(query))
    );
  });

  // Copy share link to clipboard
  const copyShareLink = async (shareToken: string) => {
    const shareUrl = `${window.location.origin}/share/${shareToken}`;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopiedShareLink(shareToken);
      setTimeout(() => setCopiedShareLink(null), 2000);
      toast({
        title: "Share link copied to clipboard",
        duration: 2000,
      });
    } catch (err) {
      toast({
        title: "Failed to copy link",
        variant: "destructive",
        duration: 2000,
      });
    }
  };

  // Handle share toggle
  const handleShareToggle = async (chat: Chat, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!onToggleShare || typeof chat.id !== 'string') return;
    try {
      const currentShareable = (chat as any).shareable || false;
      await onToggleShare(chat.id, !currentShareable);
      toast({
        title: !currentShareable ? "Chat is now shareable" : "Chat sharing disabled",
        duration: 2000,
      });
    } catch (err) {
      toast({
        title: "Failed to update sharing",
        variant: "destructive",
        duration: 2000,
      });
    }
  };

  return (
    <div className={`bg-secondary/50 border-r border-border flex-col transition-all duration-300 hidden md:flex ${isSidebarCollapsed ? 'w-20' : 'w-64'}`}>
      <div className={`p-4 border-b border-border flex ${isSidebarCollapsed ? 'justify-center' : 'justify-between items-center'}`}>
        {!isSidebarCollapsed && (
          <div className="flex items-center gap-2">
            <Button onClick={() => navigate('/home')} variant="ghost" size="icon" className="w-8 h-8 flex-shrink-0" title="Home">
              <Home className="w-5 h-5"/>
            </Button>
            <h1 className="text-lg font-semibold">Conversations</h1>
          </div>
        )}
        {isSidebarCollapsed && (
          <Button onClick={() => navigate('/home')} variant="ghost" size="icon" className="w-8 h-8 flex-shrink-0" title="Home">
            <Home className="w-5 h-5"/>
          </Button>
        )}
        <Button onClick={handleNewChat} variant="ghost" size="icon" className="w-8 h-8 flex-shrink-0" title="New Chat">
          <Plus className="w-5 h-5"/>
        </Button>
      </div>

      {/* Search bar */}
      {!isSidebarCollapsed && (
        <div className="p-2 border-b border-border">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Search chats..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-8"
            />
            {searchQuery && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-0 top-1/2 transform -translate-y-1/2 h-6 w-6"
                onClick={() => setSearchQuery("")}
              >
                <X className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {/* Show persisted chats even if messages not yet loaded; hide only pure local/draft empties */}
        {filteredChats
          .filter(chat => {
            const idStr = String(chat.id ?? "");
            const isPersisted = typeof chat.id === 'string' && !/^local-|^draft-/.test(idStr);
            const hasMsgs = Array.isArray(chat.messages) && chat.messages.length > 0;
            return isPersisted || hasMsgs;
          })
          .map(chat => (
          <div key={String(chat.id)} className={`w-full flex items-center gap-1 group rounded-md ${activeChatId === chat.id ? `bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white` : 'hover:bg-accent'}`}>
            <button
              onClick={() => setActiveChatId(chat.id)}
              onDoubleClick={(e) => { if (!isSidebarCollapsed) startRename(chat); }}
              disabled={renamingId === chat.id}
              className="flex-1 text-left flex items-center gap-3 px-3 py-2 text-sm truncate disabled:pointer-events-none"
            >
              <MessageSquare className="w-5 h-5 flex-shrink-0"/>
              {!isSidebarCollapsed && (renamingId === chat.id ? (
                <input
                  ref={inputRef}
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onBlur={submitRename}
                  onKeyDown={(e) => e.key === 'Enter' && submitRename()}
                  className="bg-transparent w-full outline-none"
                />
              ) : (
                <span className="truncate">{chat.name}</span>
              ))}
            </button>
            {!isSidebarCollapsed && (
              <div className="pr-1 flex items-center gap-1">
                {/* Share button */}
                {typeof chat.id === 'string' && onShareChat && onToggleShare && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        onClick={(e) => e.stopPropagation()}
                        variant="ghost"
                        size="icon"
                        title="Share chat"
                        className={`w-8 h-8 opacity-0 group-hover:opacity-100 ${activeChatId === chat.id ? 'opacity-100' : ''}`}
                      >
                        <Share2 className="w-4 h-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onClick={async (e) => {
                          e.stopPropagation();
                          const currentShareable = (chat as any).shareable || false;
                          await handleShareToggle(chat, e as any);
                        }}
                      >
                        {(chat as any).shareable ? (
                          <>
                            <X className="w-4 h-4 mr-2" />
                            Disable sharing
                          </>
                        ) : (
                          <>
                            <Share2 className="w-4 h-4 mr-2" />
                            Enable sharing
                          </>
                        )}
                      </DropdownMenuItem>
                      {(chat as any).shareable && (chat as any).share_token && (
                        <DropdownMenuItem
                          onClick={async (e) => {
                            e.stopPropagation();
                            await copyShareLink((chat as any).share_token);
                          }}
                        >
                          {copiedShareLink === (chat as any).share_token ? (
                            <>
                              <Check className="w-4 h-4 mr-2" />
                              Link copied!
                            </>
                          ) : (
                            <>
                              <Copy className="w-4 h-4 mr-2" />
                              Copy share link
                            </>
                          )}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                {/* Delete button */}
                <Button
                  onClick={(e) => { e.stopPropagation(); handleDeleteChat(chat.id); }}
                  variant="ghost"
                  size="icon"
                  title="Delete chat"
                  className={`w-8 h-8 opacity-0 group-hover:opacity-100 ${activeChatId === chat.id ? 'opacity-100' : ''}`}
                >
                  <Trash2 className="w-4 h-4 text-red-500" />
                </Button>
              </div>
            )}
          </div>
        ))}
        {/* Optional empty state when no conversations have started yet */}
        {filteredChats.filter(chat => {
          const idStr = String(chat.id ?? "");
          const isPersisted = typeof chat.id === 'string' && !/^local-|^draft-/.test(idStr);
          const hasMsgs = Array.isArray(chat.messages) && chat.messages.length > 0;
          return isPersisted || hasMsgs;
        }).length === 0 && (
          <div className="text-xs text-muted-foreground px-2 py-4">
            {searchQuery ? "No chats match your search." : "No conversations yet. Type a prompt to start."}
          </div>
        )}
      </div>

      <div className="p-2 border-t border-border space-y-1">
        <div className={`p-2 ${isSidebarCollapsed ? 'space-y-2' : ''}`}>
          {!isSidebarCollapsed && <label className="px-1 text-sm font-medium text-muted-foreground">Theme</label>}
          <div className={`flex ${isSidebarCollapsed ? 'justify-center' : 'justify-start'} gap-2 mt-1`}>
            {themes.map(t => (
              <button
                key={t.name}
                onClick={() => setColorTheme(t.name)}
                className={`w-6 h-6 rounded-full focus:outline-none focus:ring-2 focus:ring-offset-2 ring-offset-background bg-gradient-to-br ${getThemeGradient(t.name)} ${colorTheme === t.name ? 'ring-2 ring-primary' : 'hover:ring-1 ring-gray-400'}`}
                title={t.name.charAt(0).toUpperCase() + t.name.slice(1)}
              />
            ))}
          </div>
        </div>

        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          title={theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
          className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent ${isSidebarCollapsed ? 'justify-center' : ''}`}
        >
          {theme === 'dark' ? <Sun className="w-5 h-5"/> : <Moon className="w-5 h-5"/>}
          {!isSidebarCollapsed && <span>{theme === 'dark' ? 'Light' : 'Dark'} Mode</span>}
        </button>

        <button
          onClick={() => { onOpenSettings ? onOpenSettings() : setView('settings'); }}
          title="Settings"
          className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent ${isSidebarCollapsed ? 'justify-center' : ''}`}
        >
          <Settings className="w-5 h-5"/>
          {!isSidebarCollapsed && <span>Settings</span>}
        </button>

        {!desktopLocal && (
          <>
            <button
              onClick={handleLogout}
              title="Logout"
              className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent ${isSidebarCollapsed ? 'justify-center' : ''}`}
            >
              <LogOut className="w-5 h-5"/>
              {!isSidebarCollapsed && <span>Logout</span>}
            </button>

            <button
              onClick={handleDeleteAccount}
              title="Delete Account"
              className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-destructive hover:text-destructive-foreground ${isSidebarCollapsed ? 'justify-center' : ''}`}
            >
              <UserX className="w-5 h-5"/>
              {!isSidebarCollapsed && <span>Delete Account</span>}
            </button>
          </>
        )}

        <div className="border-t border-border my-1"></div>

        <button
          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
          title="Collapse"
          className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent ${isSidebarCollapsed ? 'justify-center' : ''}`}
        >
          <ChevronsLeft className={`w-5 h-5 transition-transform duration-300 ${isSidebarCollapsed ? 'rotate-180' : ''}`} />
          {!isSidebarCollapsed && <span>Collapse</span>}
        </button>
      </div>
    </div>
  );
};
