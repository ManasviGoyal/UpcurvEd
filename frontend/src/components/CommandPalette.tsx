// Keyboard route to the things the toolbar already does.
//
// Deliberately a *second* path, not a replacement: the dropdowns stay exactly as
// they are, so nothing changes for anyone using the mouse. Everything here reads
// from the same arrays and translation keys the dropdowns use, so the palette
// cannot list an option the toolbar does not have.
import { GraduationCap, HelpCircle, MessageSquarePlus, Sparkles } from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useLanguage } from "@/lib/i18n";

type CommandPaletteProps<TGeneration extends string, TLevel extends string> = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  generationTypes: readonly TGeneration[];
  levels: readonly TLevel[];
  onSelectGeneration: (value: TGeneration) => void;
  onSelectLevel: (value: TLevel) => void;
  onOpenHelp: () => void;
  onNewChat: () => void;
  /** Generation and level changes are ignored mid-run, matching the disabled selects. */
  disableGenerationChanges?: boolean;
};

export function CommandPalette<TGeneration extends string, TLevel extends string>({
  open,
  onOpenChange,
  generationTypes,
  levels,
  onSelectGeneration,
  onSelectLevel,
  onOpenHelp,
  onNewChat,
  disableGenerationChanges = false,
}: CommandPaletteProps<TGeneration, TLevel>) {
  const { t } = useLanguage();

  const run = (action: () => void) => {
    onOpenChange(false);
    action();
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title={t("palette.title")}>
      <CommandInput placeholder={t("palette.placeholder")} />
      <CommandList>
        <CommandEmpty>{t("palette.empty")}</CommandEmpty>

        {!disableGenerationChanges && (
          <>
            <CommandGroup heading={t("palette.group.generate")}>
              {generationTypes.map((type) => (
                <CommandItem
                  key={type}
                  // Searchable by both the visible name and its description, so
                  // typing "printable" finds the static worksheet.
                  value={`${t(`chat.gen.${type}`)} ${t(`chat.gen.${type}.desc`)}`}
                  onSelect={() => run(() => onSelectGeneration(type))}
                >
                  <Sparkles className="mr-2 h-4 w-4" aria-hidden="true" />
                  <span>{t(`chat.gen.${type}`)}</span>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t("palette.group.level")}>
              {levels.map((level) => (
                <CommandItem
                  key={level}
                  value={`${t("palette.group.level")} ${t(`chat.level.${level}`)} ${t(`chat.level.${level}.desc`)}`}
                  onSelect={() => run(() => onSelectLevel(level))}
                >
                  <GraduationCap className="mr-2 h-4 w-4" aria-hidden="true" />
                  <span>{t(`chat.level.${level}`)}</span>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />
          </>
        )}

        <CommandGroup heading={t("palette.group.other")}>
          <CommandItem value={t("palette.newChat")} onSelect={() => run(onNewChat)}>
            <MessageSquarePlus className="mr-2 h-4 w-4" aria-hidden="true" />
            <span>{t("palette.newChat")}</span>
          </CommandItem>
          <CommandItem value={t("palette.openHelp")} onSelect={() => run(onOpenHelp)}>
            <HelpCircle className="mr-2 h-4 w-4" aria-hidden="true" />
            <span>{t("palette.openHelp")}</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

export default CommandPalette;
