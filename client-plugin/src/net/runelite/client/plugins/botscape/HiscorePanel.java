package net.runelite.client.plugins.botscape;

import static net.runelite.client.plugins.botscape.BotScapeUi.GOLD;
import static net.runelite.client.plugins.botscape.BotScapeUi.MUTED;
import static net.runelite.client.plugins.botscape.BotScapeUi.TEXT;

import java.awt.BorderLayout;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.GridLayout;
import java.util.Map;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.ImageIcon;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingConstants;
import javax.swing.SwingUtilities;
import net.runelite.api.Skill;
import net.runelite.client.game.SkillIconManager;
import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.PluginPanel;
import net.runelite.client.ui.components.IconTextField;

/**
 * User-requested: the hiscore lookup, from this server's hiscores (RuneLite's own panel asks Jagex's,
 * which don't know Bot Scape's players). Type a name, or right-click a player and Lookup.
 */
class HiscorePanel extends PluginPanel
{
	/** The skills in the order of the game's skill tab (three columns). */
	private static final Skill[] ORDER = {
		Skill.ATTACK, Skill.HITPOINTS, Skill.MINING, Skill.STRENGTH, Skill.AGILITY, Skill.SMITHING,
		Skill.DEFENCE, Skill.HERBLORE, Skill.FISHING, Skill.RANGED, Skill.THIEVING, Skill.COOKING,
		Skill.PRAYER, Skill.CRAFTING, Skill.FIREMAKING, Skill.MAGIC, Skill.FLETCHING, Skill.WOODCUTTING,
		Skill.RUNECRAFT, Skill.SLAYER, Skill.FARMING, Skill.CONSTRUCTION, Skill.HUNTER,
	};

	private final SkillIconManager icons;
	private final IconTextField search = new IconTextField();
	private final JPanel results = new JPanel();

	HiscorePanel(SkillIconManager icons)
	{
		super(true);
		this.icons = icons;
		setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
		setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));
		JLabel title = BotScapeUi.bold("Bot Scape hiscores", GOLD);
		title.setAlignmentX(Component.LEFT_ALIGNMENT);
		add(title);
		add(Box.createVerticalStrut(6));
		search.setIcon(IconTextField.Icon.SEARCH);
		search.setPreferredSize(new Dimension(PANEL_WIDTH - 20, 30));
		search.setMaximumSize(new Dimension(PANEL_WIDTH - 20, 30));
		search.setBackground(ColorScheme.DARKER_GRAY_COLOR);
		search.setAlignmentX(Component.LEFT_ALIGNMENT);
		search.addActionListener(e -> lookup(search.getText()));
		add(search);
		add(Box.createVerticalStrut(8));
		results.setLayout(new BoxLayout(results, BoxLayout.Y_AXIS));
		results.setOpaque(false);
		results.setAlignmentX(Component.LEFT_ALIGNMENT);
		add(results);
	}

	/** Looks up [name] (off the UI thread) and shows its levels, XP and ranks. */
	void lookup(String name)
	{
		String who = name == null ? "" : name.replace(' ', ' ').trim();
		if (who.isEmpty())
		{
			return;
		}
		search.setText(who);
		search.setIcon(IconTextField.Icon.LOADING);
		new Thread(() -> {
			Map<String, Object> data;
			try
			{
				data = Gateway.map(Gateway.getUrl(Gateway.base() + "/hiscores/" + Gateway.enc(who)));
			}
			catch (Exception e)
			{
				data = Map.of("error", "The server didn't answer.");
			}
			Map<String, Object> shown = data;
			SwingUtilities.invokeLater(() -> show(shown));
		}, "botscape-hiscore").start();
	}

	private void show(Map<String, Object> data)
	{
		search.setIcon(IconTextField.Icon.SEARCH);
		results.removeAll();
		String error = Gateway.str(data.get("error"));
		if (!error.isEmpty())
		{
			results.add(BotScapeUi.small(error, BotScapeUi.RED));
			results.revalidate();
			results.repaint();
			return;
		}
		results.add(BotScapeUi.bold(Gateway.str(data.get("name")), TEXT));
		String group = Gateway.str(data.get("group"));
		if (!group.isEmpty())
		{
			results.add(BotScapeUi.small(group, MUTED));
		}
		results.add(Box.createVerticalStrut(6));
		Map<String, Object> skills = Gateway.map(data.get("skills"));
		JPanel grid = new JPanel(new GridLayout(0, 3, 4, 4));
		grid.setOpaque(false);
		grid.setAlignmentX(Component.LEFT_ALIGNMENT);
		for (Skill skill : ORDER)
		{
			String key = skill == Skill.RUNECRAFT ? "runecrafting" : skill.getName().toLowerCase();
			Map<String, Object> row = Gateway.map(skills.get(key));
			int level = row.isEmpty() ? 1 : Gateway.num(row.get("level"));
			JLabel cell = new JLabel(String.valueOf(level), new ImageIcon(icons.getSkillImage(skill, true)), SwingConstants.LEFT);
			cell.setForeground(TEXT);
			cell.setIconTextGap(6);
			long xp = row.isEmpty() ? 0 : ((Number) row.getOrDefault("xp", 0)).longValue();
			int rank = row.isEmpty() ? -1 : Gateway.num(row.get("rank"));
			cell.setToolTipText(String.format("<html>%s<br>Rank: %s<br>XP: %,d</html>", skill.getName(),
				rank > 0 ? String.format("%,d", rank) : "unranked", xp));
			grid.add(cell);
		}
		results.add(grid);
		results.add(Box.createVerticalStrut(8));
		long totalXp = ((Number) data.getOrDefault("totalXp", 0)).longValue();
		JPanel total = new JPanel(new BorderLayout());
		total.setOpaque(false);
		total.setAlignmentX(Component.LEFT_ALIGNMENT);
		total.add(BotScapeUi.bold("Total level " + Gateway.num(data.get("totalLevel")), GOLD), BorderLayout.WEST);
		total.add(BotScapeUi.small("Rank " + String.format("%,d", Gateway.num(data.get("rank"))), MUTED), BorderLayout.EAST);
		results.add(total);
		results.add(BotScapeUi.small(String.format("%,d XP", totalXp), MUTED));
		results.revalidate();
		results.repaint();
	}
}
