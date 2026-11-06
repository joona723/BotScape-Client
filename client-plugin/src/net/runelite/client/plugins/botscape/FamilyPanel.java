package net.runelite.client.plugins.botscape;

import static net.runelite.client.plugins.botscape.BotScapeUi.GOLD;
import static net.runelite.client.plugins.botscape.BotScapeUi.MUTED;
import static net.runelite.client.plugins.botscape.BotScapeUi.TEXT;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.GridLayout;
import java.awt.RenderingHints;
import java.util.List;
import java.util.Map;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JComponent;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.FontManager;
import net.runelite.client.ui.PluginPanel;

/** The family: the main and its clones, progress to the next clone, and the shared bank. */
class FamilyPanel extends PluginPanel
{
	private final BotScapeData data;
	private final JPanel body = new JPanel();

	FamilyPanel(BotScapeData data)
	{
		super(true);
		this.data = data;
		setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
		setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));
		body.setLayout(new BoxLayout(body, BoxLayout.Y_AXIS));
		body.setOpaque(false);
		body.setAlignmentX(Component.LEFT_ALIGNMENT);
		add(body);
		data.addListener(this::paint);
		paint();
	}

	private void paint()
	{
		body.removeAll();
		body.add(BotScapeUi.bold("Bot Scape", GOLD));
		body.add(Box.createVerticalStrut(2));
		body.add(BotScapeUi.small(data.offline() ? "Server offline" : "Server online",
			data.offline() ? BotScapeUi.RED : new Color(0x5fd38d)));

		Map<String, Object> fam = data.family();
		int total = Gateway.num(fam.get("totalLevel"));
		// -1: members need no levels; nextUnlockAt null: the group is full (server's group rules).
		int unlockedRaw = Gateway.num(fam.get("unlocked"));
		boolean unlimited = unlockedRaw < 0;
		int unlocked = unlimited ? Integer.MAX_VALUE : unlockedRaw;
		boolean full = fam.get("nextUnlockAt") == null;
		int next = full ? total : Gateway.num(fam.get("nextUnlockAt"));
		Map<String, Object> rules = Gateway.map(fam.get("rules"));
		int step = rules.containsKey("levelsPerMember") ? Gateway.num(rules.get("levelsPerMember")) : 100;
		List<Object> clones = Gateway.list(fam.containsKey("members") ? fam.get("members") : fam.get("clones"));
		// User-requested: members the group's total level hasn't unlocked yet aren't shown or counted.
		long open = clones.stream().filter(o -> Boolean.TRUE.equals(Gateway.map(o).get("unlocked"))).count();

		// Group summary with progress to the next member slot.
		body.add(BotScapeUi.header("Group", null));
		BotScapeUi.Card summary = new BotScapeUi.Card();
		JPanel stats = new JPanel(new GridLayout(1, 2));
		stats.setOpaque(false);
		stats.add(stat("Total level", String.valueOf(total)));
		stats.add(stat("Members", open + " / " + (unlimited ? "∞" : String.valueOf(unlocked))));
		JPanel inner = new JPanel(new BorderLayout(0, 6));
		inner.setOpaque(false);
		inner.add(stats, BorderLayout.NORTH);
		double progress = unlimited || full || step <= 0 ? 1 : (total - (next - step)) / (double) step;
		inner.add(new Progress(Math.max(0, Math.min(1, progress))), BorderLayout.CENTER);
		String nextText = unlimited ? "Members need no levels"
			: full ? "Your group is full"
			: "Next member at total level " + next + " · " + Math.max(0, next - total) + " to go";
		inner.add(BotScapeUi.small(nextText, MUTED), BorderLayout.SOUTH);
		summary.add(inner, BorderLayout.CENTER);
		body.add(summary);

		// Characters.
		BotScapeUi.RoundButton make = new BotScapeUi.RoundButton("+ Add member", GOLD, new Color(0xf09a10));
		make.setForeground(Color.BLACK);
		make.setEnabled(clones.size() < unlocked);
		make.setToolTipText(clones.size() < unlocked ? "Add a member to your group"
			: full ? "Your group is full" : "Reach total level " + next + " to unlock another member");
		make.addActionListener(e -> newClone());
		body.add(BotScapeUi.header("Characters", make));
		body.add(character(data.main(), "main", true));
		for (Object o : clones)
		{
			Map<String, Object> c = Gateway.map(o);
			if (!Boolean.TRUE.equals(c.get("unlocked")))
			{
				continue;
			}
			body.add(Box.createVerticalStrut(4));
			body.add(character(Gateway.str(c.get("name")), "member " + Gateway.num(c.get("index")), true,
				Gateway.str(c.get("display"))));
		}

		// Shared bank.
		Map<String, Object> state = data.familyState();
		List<Object> items = Gateway.list(state.get("bank"));
		body.add(BotScapeUi.header("Shared bank", BotScapeUi.small(items.isEmpty() ? "" : items.size() + " items", MUTED)));
		if (state.isEmpty())
		{
			body.add(BotScapeUi.small("Shown while someone in the family is online.", MUTED));
		}
		else if (items.isEmpty())
		{
			body.add(BotScapeUi.small("The bank is empty.", MUTED));
		}
		else
		{
			BotScapeUi.Card bank = new BotScapeUi.Card();
			JPanel list = new JPanel();
			list.setLayout(new BoxLayout(list, BoxLayout.Y_AXIS));
			list.setOpaque(false);
			for (Object o : items)
			{
				Map<String, Object> item = Gateway.map(o);
				list.add(row(Gateway.str(item.get("name")), fmt(Gateway.num(item.get("count")))));
			}
			bank.add(list, BorderLayout.CENTER);
			body.add(bank);
		}
		body.revalidate();
		body.repaint();
	}

	private Component character(String name, String role, boolean unlocked)
	{
		return character(name, role, unlocked, "");
	}

	/** [shown]: the name a group member with a hidden login name shows (blank: its login name). */
	private Component character(String name, String role, boolean unlocked, String shown)
	{
		String s = unlocked ? data.status(name) : "locked";
		BotScapeUi.Card card = new BotScapeUi.Card();
		card.setAccent(s.equals("online") ? BotScapeUi.GREEN : null);
		JPanel text = new JPanel();
		text.setLayout(new BoxLayout(text, BoxLayout.Y_AXIS));
		text.setOpaque(false);
		text.add(BotScapeUi.label(shown.isEmpty() ? name : shown, role.equals("main") ? GOLD : TEXT, FontManager.getRunescapeBoldFont()));
		text.add(BotScapeUi.small(role, MUTED));
		String doing = data.activity(name);
		if (!doing.isEmpty() && unlocked)
		{
			text.add(BotScapeUi.small("<html><div style='width:130px'>" + doing.replace("<", "&lt;") + "</div></html>",
				new Color(0x5fd38d)));
		}
		card.add(text, BorderLayout.CENTER);
		JPanel right = new JPanel(new BorderLayout());
		right.setOpaque(false);
		right.add(new BotScapeUi.Pill(s, BotScapeUi.statusColor(s)), BorderLayout.NORTH);
		card.add(right, BorderLayout.EAST);
		return card;
	}

	private static JComponent stat(String label, String value)
	{
		JPanel p = new JPanel();
		p.setLayout(new BoxLayout(p, BoxLayout.Y_AXIS));
		p.setOpaque(false);
		p.add(BotScapeUi.label(value, Color.WHITE, FontManager.getRunescapeBoldFont()));
		p.add(BotScapeUi.small(label, MUTED));
		return p;
	}

	private static JComponent row(String left, String right)
	{
		JPanel r = new JPanel(new BorderLayout(6, 0));
		r.setOpaque(false);
		r.setAlignmentX(Component.LEFT_ALIGNMENT);
		r.setMaximumSize(new Dimension(Integer.MAX_VALUE, 18));
		r.add(BotScapeUi.small(left, TEXT), BorderLayout.WEST);
		r.add(BotScapeUi.small(right, GOLD), BorderLayout.EAST);
		return r;
	}

	private void newClone()
	{
		String name = JOptionPane.showInputDialog(this, "Name for the new group member (max 12 letters):", "Add member",
			JOptionPane.PLAIN_MESSAGE);
		if (name == null || name.isBlank())
		{
			return;
		}
		new Thread(() ->
		{
			String msg;
			try
			{
				Map<String, Object> r = Gateway.map(Gateway.post("/families/" + Gateway.enc(data.main()) + "/clones",
					Map.of("name", name.strip().toLowerCase())));
				msg = r.containsKey("error") ? Gateway.str(r.get("error"))
					: (Gateway.str(r.get("display")).isEmpty() ? Gateway.str(r.get("name")) : Gateway.str(r.get("display"))) + " joined your group as member " + Gateway.num(r.get("index"))
					+ ". They log in with your main's password.";
			}
			catch (Exception e)
			{
				msg = "Server offline.";
			}
			String m = msg;
			SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(this, m));
			data.refresh();
		}, "botscape-clone").start();
	}

	private static String fmt(int n)
	{
		if (n >= 10_000_000)
		{
			return n / 1_000_000 + "M";
		}
		if (n >= 100_000)
		{
			return n / 1000 + "K";
		}
		return String.format("%,d", n);
	}

	/** A slim rounded progress bar. */
	private static final class Progress extends JComponent
	{
		private final double fraction;

		Progress(double fraction)
		{
			this.fraction = fraction;
			setPreferredSize(new Dimension(10, 6));
		}

		@Override
		protected void paintComponent(Graphics graphics)
		{
			Graphics2D g = (Graphics2D) graphics.create();
			g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
			g.setColor(ColorScheme.DARK_GRAY_COLOR);
			g.fillRoundRect(0, 0, getWidth(), getHeight(), 6, 6);
			g.setColor(GOLD);
			g.fillRoundRect(0, 0, (int) (getWidth() * fraction), getHeight(), 6, 6);
			g.dispose();
		}
	}
}
