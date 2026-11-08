package net.runelite.client.plugins.botscape;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.GridLayout;
import java.awt.Window;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import javax.swing.BorderFactory;
import javax.swing.DefaultListCellRenderer;
import javax.swing.DefaultListModel;
import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextField;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import net.runelite.client.ui.ColorScheme;

/**
 * User-requested: the admin commands as a menu, opened with the § key. The client opens it only when the server says
 * this player is an admin (GET /players/{name}/admin-menu), and the server checks admin again for every command
 * (POST /players/{name}/command runs it as the player playing in this client, never for a bot).
 * Quests: pick one, then Start stepper / Prev / Next / Stepper off, or Complete / Reset it.
 */
class AdminMenu
{
	private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(AdminMenu.class);
	private static AdminMenu open;

	private final JDialog dialog;
	private final Supplier<String> player;
	private final DefaultListModel<Map<String, Object>> model = new DefaultListModel<>();
	private final JList<Map<String, Object>> list = new JList<>(model);
	private final JTextField filter = new JTextField();
	private final JLabel status = new JLabel(" ");
	private List<Map<String, Object>> quests = new ArrayList<>();

	/** Asks the server (off the client thread) and opens the menu only for an admin. */
	static void toggle(Window owner, Supplier<String> player)
	{
		if (open != null && open.dialog.isShowing())
		{
			open.dialog.dispose();
			open = null;
			return;
		}
		new Thread(() ->
		{
			Map<String, Object> menu = fetch(player.get());
			if (menu == null || !Boolean.TRUE.equals(menu.get("admin")))
			{
				return;   // not an admin (or offline): no menu at all
			}
			SwingUtilities.invokeLater(() ->
			{
				open = new AdminMenu(owner, player);
				open.show(menu);
			});
		}, "botscape-admin-menu").start();
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> fetch(String name)
	{
		if (name == null)
		{
			return null;
		}
		try
		{
			Object answer = Gateway.get("/players/" + Gateway.enc(name) + "/admin-menu");
			return answer instanceof Map ? (Map<String, Object>) answer : null;
		}
		catch (Exception e)
		{
			log.warn("Bot Scape: admin menu failed", e);
			return null;
		}
	}

	private AdminMenu(Window owner, Supplier<String> player)
	{
		this.player = player;
		dialog = new JDialog(owner, "Bot Scape admin", java.awt.Dialog.ModalityType.MODELESS);
		dialog.setDefaultCloseOperation(JDialog.DISPOSE_ON_CLOSE);

		JPanel root = new JPanel(new BorderLayout(0, 8));
		root.setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));
		root.setBackground(ColorScheme.DARK_GRAY_COLOR);

		JLabel title = new JLabel("Quests  ·  admin only (§ closes)");
		title.setForeground(BotScapeUi.GOLD);
		filter.setToolTipText("Find a quest");
		filter.getDocument().addDocumentListener(new DocumentListener()
		{
			public void insertUpdate(DocumentEvent e) { refill(); }
			public void removeUpdate(DocumentEvent e) { refill(); }
			public void changedUpdate(DocumentEvent e) { refill(); }
		});
		JPanel top = new JPanel(new BorderLayout(0, 6));
		top.setOpaque(false);
		top.add(title, BorderLayout.NORTH);
		top.add(filter, BorderLayout.SOUTH);
		root.add(top, BorderLayout.NORTH);

		list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
		list.setBackground(ColorScheme.DARKER_GRAY_COLOR);
		list.setCellRenderer(new DefaultListCellRenderer()
		{
			@Override
			public Component getListCellRendererComponent(JList<?> l, Object value, int index, boolean selected, boolean focus)
			{
				@SuppressWarnings("unchecked") Map<String, Object> q = (Map<String, Object>) value;
				String state = String.valueOf(q.get("status"));
				int steps = ((Number) q.getOrDefault("steps", 0)).intValue();
				String text = q.get("name") + (steps > 0 ? "   (" + steps + " steps)" : "   (no steps)");
				JLabel label = (JLabel) super.getListCellRendererComponent(l, text, index, selected, focus);
				label.setForeground(selected ? Color.WHITE : "done".equals(state) ? new Color(0x3ecf6e)
					: "started".equals(state) ? new Color(0xe8b64c) : new Color(0xf0716a));
				label.setBackground(selected ? new Color(0x4a3a1a) : ColorScheme.DARKER_GRAY_COLOR);
				return label;
			}
		});
		JScrollPane scroll = new JScrollPane(list);
		scroll.setPreferredSize(new Dimension(320, 360));
		root.add(scroll, BorderLayout.CENTER);

		JPanel buttons = new JPanel(new GridLayout(0, 3, 6, 6));
		buttons.setOpaque(false);
		buttons.add(button("Start stepper", () -> selected("quest active ")));
		buttons.add(button("◀ Prev", () -> "quest prev"));
		buttons.add(button("Next ▶", () -> "quest next"));
		buttons.add(button("Stepper off", () -> "quest active off"));
		buttons.add(button("Complete", () -> selected("quest complete ")));
		buttons.add(button("Reset", () -> selected("quest reset ")));
		status.setForeground(BotScapeUi.MUTED);
		JPanel bottom = new JPanel(new BorderLayout(0, 6));
		bottom.setOpaque(false);
		bottom.add(buttons, BorderLayout.CENTER);
		bottom.add(status, BorderLayout.SOUTH);
		root.add(bottom, BorderLayout.SOUTH);

		dialog.setContentPane(root);
		dialog.pack();
		dialog.setLocationRelativeTo(owner);
	}

	private String selected(String prefix)
	{
		Map<String, Object> q = list.getSelectedValue();
		if (q == null)
		{
			status.setText("Pick a quest first.");
			return null;
		}
		return prefix + String.valueOf(q.get("name")).toLowerCase();
	}

	private JButton button(String text, Supplier<String> command)
	{
		JButton b = new JButton(text);
		b.setFocusable(false);
		b.addActionListener(e ->
		{
			String cmd = command.get();
			if (cmd != null)
			{
				send(cmd);
			}
		});
		return b;
	}

	/** Runs the command on the server (it checks admin again), then reloads the list and the stepper line. */
	private void send(String command)
	{
		String name = player.get();
		status.setText("…");
		new Thread(() ->
		{
			String result;
			try
			{
				Object answer = Gateway.post("/players/" + Gateway.enc(name) + "/command", Map.of("text", command));
				result = answer instanceof Map && ((Map<?, ?>) answer).get("error") != null
					? String.valueOf(((Map<?, ?>) answer).get("error")) : null;
			}
			catch (Exception e)
			{
				result = "Failed: " + e.getMessage();
			}
			Map<String, Object> menu = fetch(name);
			String error = result;
			SwingUtilities.invokeLater(() ->
			{
				if (menu != null && Boolean.TRUE.equals(menu.get("admin")))
				{
					show(menu);
				}
				if (error != null)
				{
					status.setText(error);
				}
			});
		}, "botscape-admin-command").start();
	}

	@SuppressWarnings("unchecked")
	private void show(Map<String, Object> menu)
	{
		Object q = menu.get("quests");
		quests = q instanceof List ? (List<Map<String, Object>>) q : new ArrayList<>();
		refill();
		Object stepper = menu.get("stepper");
		if (stepper instanceof Map)
		{
			Map<String, Object> s = (Map<String, Object>) stepper;
			status.setText("Stepper: " + s.get("quest") + "  step " + num(s.get("step")) + "/" + num(s.get("steps")));
		}
		else
		{
			status.setText("Stepper off.");
		}
		if (!dialog.isShowing())
		{
			dialog.setVisible(true);
		}
	}

	private static String num(Object o)
	{
		return o instanceof Number ? String.valueOf(((Number) o).intValue()) : String.valueOf(o);
	}

	private void refill()
	{
		Map<String, Object> keep = list.getSelectedValue();
		String find = filter.getText().trim().toLowerCase();
		model.clear();
		for (Map<String, Object> q : quests)
		{
			if (find.isEmpty() || String.valueOf(q.get("name")).toLowerCase().contains(find))
			{
				model.addElement(q);
				if (keep != null && keep.get("name").equals(q.get("name")))
				{
					list.setSelectedIndex(model.size() - 1);
				}
			}
		}
	}
}
