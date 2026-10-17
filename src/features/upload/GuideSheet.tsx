import { SideSheet } from '@/components/ui/overlays'
import { ko } from '@/i18n/ko'

/** Illustrator / Figma separation guide. */
export function GuideSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const g = ko.guide
  return (
    <SideSheet open={open} onOpenChange={onOpenChange} title={g.title}>
      <div className="space-y-6 text-sm">
        <p className="text-ink-muted">{g.intro}</p>
        <section>
          <h3 className="mb-2 font-semibold">{g.namesTitle}</h3>
          <table className="w-full text-left text-xs">
            <tbody>
              {g.names.map((n) => (
                <tr key={n.what} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-2 font-medium">{n.what}</td>
                  <td className="py-1.5 pr-2 font-mono">{n.name}</td>
                  <td className="py-1.5 text-ink-muted">{n.alt}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        {[
          [g.illustratorTitle, g.illustrator],
          [g.figmaTitle, g.figma],
        ].map(([title, steps]) => (
          <section key={title as string}>
            <h3 className="mb-2 font-semibold">{title as string}</h3>
            <ol className="list-decimal space-y-1 pl-5">
              {(steps as readonly string[]).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </SideSheet>
  )
}
