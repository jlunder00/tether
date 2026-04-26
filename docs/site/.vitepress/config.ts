import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Tether',
  description: 'Documentation for Tether — an AI-powered personal task management system',

  themeConfig: {
    logo: '/logo.svg',

    nav: [
      { text: 'Using Tether', link: '/using-tether/' },
      { text: 'Self-Hosting', link: '/self-hosting/' },
      { text: 'Development', link: '/development/' },
    ],

    sidebar: {
      '/using-tether/': [
        {
          text: 'Using Tether',
          items: [
            { text: 'Overview', link: '/using-tether/' },
            { text: 'Telegram Bot', link: '/using-tether/bot' },
            { text: 'Dashboard', link: '/using-tether/dashboard' },
            { text: 'Anchors & Schedule', link: '/using-tether/anchors' },
            { text: 'Tasks & Kanban', link: '/using-tether/tasks-and-kanban' },
            { text: 'Calendar', link: '/using-tether/calendar' },
            { text: 'Context & Projects', link: '/using-tether/context' },
            { text: 'MCP & Claude Code', link: '/using-tether/mcp' },
          ],
        },
      ],

      '/self-hosting/': [
        {
          text: 'Self-Hosting & Configuration',
          items: [
            { text: 'Overview', link: '/self-hosting/' },
            { text: 'Installation', link: '/self-hosting/installation' },
            { text: 'Configuration', link: '/self-hosting/configuration' },
            { text: 'Secrets Reference', link: '/self-hosting/secrets-reference' },
            { text: 'Deployment Modes', link: '/self-hosting/deployment-modes' },
            { text: 'Upgrading', link: '/self-hosting/upgrading' },
            { text: 'Troubleshooting', link: '/self-hosting/troubleshooting' },
          ],
        },
      ],

      '/development/': [
        {
          text: 'Development',
          items: [
            { text: 'Overview', link: '/development/' },
            { text: 'Architecture', link: '/development/architecture' },
            { text: 'Bot Pipeline', link: '/development/bot-pipeline' },
            { text: 'API Reference', link: '/development/api-reference' },
            { text: 'MCP Tools', link: '/development/mcp-tools' },
            { text: 'Contributing', link: '/development/contributing' },
            { text: 'Testing', link: '/development/testing' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/jlunder00/tether' },
    ],

    footer: {
      message: 'Released under the AGPLv3 License.',
    },
  },
})
