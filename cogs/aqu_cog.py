import discord
from discord.ext import commands
import google.generativeai as genai
import json
import traceback
import os

# 🔒 Puxando a chave de forma segura por variável de ambiente
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_KEY:
    print("⚠️ AVISO: GEMINI_API_KEY não configurada nas variáveis de ambiente! A Aqua não vai funcionar.")
else:
    genai.configure(api_key=GEMINI_KEY)


class ConfirmarAcaoAqua(discord.ui.View):
    def __init__(self, message, codigo_gerado, explicacao, frase_sucesso):
        super().__init__(timeout=120.0)  # O painel expira após 2 minutos
        self.message = message
        self.codigo_gerado = codigo_gerado
        self.explicacao = explicacao
        self.frase_sucesso = frase_sucesso

    @discord.ui.button(label="Confirmar e Executar", style=discord.ButtonStyle.green, emoji="✅")
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Garante que apenas quem deu a ordem à Aqua pode clicar no botão
        if interaction.user != self.message.author:
            await interaction.response.send_message("Apenas quem deu a ordem à Aqua pode confirmar.", ephemeral=True)
            return

        await interaction.response.send_message("⚡ Aqua a executar ordens...", ephemeral=True)
        
        # Cria o ambiente com as variáveis necessárias para o código da IA funcionar
        ambiente_execucao = {
            "discord": discord,
            "message": self.message,
            "guild": self.message.guild,
            "bot": self.message.guild.me._state.零件_bot if hasattr(self.message.guild.me._state, '零件_bot') else None
        }
        
        try:
            # Transforma as linhas de texto da IA numa função assíncrona executável
            codigo_formatado = f"async def _executar_dinamico(message, guild):\n"
            for linha in self.codigo_gerado.split('\n'):
                codigo_formatado += f"    {linha}\n"
                
            # Compila e executa o código no ambiente controlado
            exec(codigo_formatado, ambiente_execucao)
            await ambiente_execucao["_executar_dinamico"](self.message, self.message.guild)
            
            # Resposta inteligente da Aqua pós-execução baseada no contexto
            await self.message.channel.send(f"🔮 **Aqua:** {self.frase_sucesso}")
            
        except Exception as e:
            erro = traceback.format_exc()
            await self.message.channel.send(f"❌ Ocorreu um erro ao executar a ação da IA:\n```py\n{erro}\n```")
        
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.red, emoji="❌")
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.message.author:
            await interaction.response.send_message("Não podes cancelar esta ação.", ephemeral=True)
            return

        await interaction.response.send_message("Ação cancelada de forma segura.", ephemeral=True)
        self.stop()


class AquaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # 1. Ignora mensagens enviadas por outros bots
        if message.author.bot:
            return

        # 2. Ativa se o nome Aqua for mencionado na mensagem
        if "aqua" in message.content.lower():
            
            # 3. Trava de Segurança Crítica: Só aceita ordens de Administradores
            if not message.author.guild_permissions.administrator:
                await message.channel.send("Não tens autoridade para dar ordens administrativas à Aqua.")
                return

            if not GEMINI_KEY:
                await message.channel.send("Erro: A chave de API da Aqua não foi configurada no sistema.")
                return

            # Mostra no Discord que ela está a "digitar" enquanto pensa
            async with message.channel.typing():
                model = genai.GenerativeModel("gemini-1.5-pro")
                
                prompt_sistema = f"""
                Você é a Aqua, uma inteligência artificial integrada como administradora deste servidor de Discord.
                O utilizador deu-te a seguinte ordem em linguagem natural: "{message.content}"
                
                Analise rigorosamente o pedido e responda ESTRITAMENTE em formato JSON com três chaves:
                1. "explicacao": Uma frase curta em português explicando EXATAMENTE o que vais fazer com base apenas nos factos fornecidos. Não invente motivos ou contextos que não foram ditos.
                2. "codigo": Linhas de código em Python puro utilizando a biblioteca discord.py para realizar a ação.
                3. "frase_sucesso": A frase em português que vais dizer após a ação ser concluída com sucesso. Ajuste o tom (seco se a ordem foi curta, detalhado se a ordem foi longa).
                
                Regras de ouro para o "codigo":
                - Tens disponíveis as variáveis: `message` (objeto da mensagem) e `guild` (objeto do servidor).
                - Podes usar `guild.channels`, `guild.roles`, `guild.members`, etc.
                - Use `await` para funções assíncronas obrigatórias do discord.py.
                - Nunca inclua marcações de markdown (como ```py) no valor do JSON. Envie apenas texto limpo.
                
                Responda APENAS o JSON estruturado, sem saudações ou textos fora dele.
                """
                
                try:
                    response = model.generate_content(
                        prompt_sistema,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    
                    # Desembrulha o JSON retornado pela IA
                    dados_ia = json.loads(response.text)
                    explicacao = dados_ia.get("explicacao", "Executar ação interpretada pela IA.")
                    codigo_gerado = dados_ia.get("codigo", "")
                    frase_sucesso = dados_ia.get("frase_sucesso", "Ordem cumprida!")
                    
                    # Se não houver código técnico gerado (ex: só estavas a conversar com ela)
                    if not codigo_gerado:
                        await message.channel.send(response.text if response.text else "Entendi o que disseste, mas não há ações a tomar no servidor.")
                        return
                        
                    # Cria e envia o painel de confirmação com os botões
                    view = ConfirmarAcaoAqua(message, codigo_gerado, explicacao, frase_sucesso)
                    
                    embed = discord.Embed(title="🔮 Aqua - Solicitação de Autorização", color=discord.Color.blue())
                    embed.add_field(name="O que vou fazer:", value=explicacao, inline=False)
                    embed.add_field(name="Código técnico gerado em tempo real:", value=f"```py\n{codigo_gerado}\n```", inline=False)
                    embed.set_footer(text="A Aqua aguarda a tua confirmação para agir.")
                    
                    await message.channel.send(embed=embed, view=view)
                    
                except Exception as e:
                    await message.channel.send(f"Houve um problema ao processar a inteligência da Aqua: {e}")


# Função obrigatória para o Discord.py carregar a Cog
async def setup(bot):
    await bot.add_cog(AquaCog(bot))
