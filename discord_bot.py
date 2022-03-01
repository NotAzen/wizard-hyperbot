import nextcord

import db
from sqlalchemy import and_
import discord_utils
import messages

intents = nextcord.Intents.default()
intents.members = True
client = nextcord.Client(intents=intents)


@client.event
async def on_ready():
    print(f'logged in as {client.user}')
    await discord_utils.update_all_user_roles()
    await discord_utils.update_all_user_nicknames()


@client.event
async def on_member_join(member):
    db.session.merge(db.User(id=str(member.id), name=member.nick))
    db.session.commit()
    await discord_utils.update_user_roles(member.id)
    await discord_utils.update_user_nickname(member.id)


@client.event
async def on_member_update(before, after):
    if before.nick != after.nick:
        print(f'{after.name} changed their nick from {before.nick} to {after.nick}')
        user = db.session.get(db.User, str(after.id)) or db.User(id=after.id)
        if after.nick == user.nick:
            return
        user.name = after.nick
        db.session.merge(user)
        db.session.commit()
        await discord_utils.update_user_nickname(str(after.id))


@client.event
async def on_user_update(before, after):
    if before.name != after.name:
        print(f'{after.name} changed their name from {before.name} to {after.name}')
        await discord_utils.update_user_nickname(str(after.id))


@client.slash_command('solve', description='Solve')
async def solve_command(ctx, solution=nextcord.SlashOption('solution', 'The solution of the level you solved.')):
    if ctx.channel.type == nextcord.ChannelType.private:
        level_solutions = db.session.query(db.Solution).where(db.Solution.text == solution)
        for level_solution in level_solutions:
            level = level_solution.level
            if discord_utils.can_user_solve(level, str(ctx.user.id)):
                await ctx.send(messages.confirm_solve.format(level_name=level.name))
                db.session.add(db.UserSolve(user_id=str(ctx.user.id), level=level))
                db.session.commit()
                await discord_utils.update_user_roles(str(ctx.user.id))
                await discord_utils.update_user_nickname(str(ctx.user.id))
                break
        else:
            await ctx.send(messages.reject_solve)
    else:
        await ctx.send(messages.use_in_dms, ephemeral=True)


@client.slash_command('unlock', description='Unlock')
async def unlock_command(ctx, unlock=nextcord.SlashOption('unlock', 'The code to unlock a secret level you found.')):
    if ctx.channel.type == nextcord.ChannelType.private:
        level_unlocks = db.session.query(db.Unlock).where(db.Unlock.text == unlock)
        for level_unlock in level_unlocks:
            level = level_unlock.level
            if discord_utils.can_user_unlock(level, str(ctx.user.id)):
                await ctx.send(messages.confirm_unlock.format(level_name=level.name))
                db.session.add(db.UserUnlock(user_id=str(ctx.user.id), level=level))
                db.session.commit()
                await discord_utils.update_user_roles(str(ctx.user.id))
                await discord_utils.update_user_nickname(str(ctx.user.id))
                break
        else:
            await ctx.send(messages.reject_unlock)
    else:
        await ctx.send(messages.use_in_dms, ephemeral=True)


@client.slash_command('recall', description='Recall a solved level')
async def recall_command(ctx, level=nextcord.SlashOption('level', 'Level name', required=True)):
    if ctx.channel.type == nextcord.ChannelType.private:
        solved_levels = discord_utils.get_solved_levels(ctx.user.id, name=level)
        if len(solved_levels) == 0:
            await ctx.send('No such level', ephemeral=True)
        else:
            embeds = []
            for level in solved_levels:
                embed = nextcord.Embed(title=f'{level.name}', url=level.get_encoded_link(db.get_setting('auth_in_link') == 'true'))
                embed.colour = int(db.get_setting('embed_color', '#000000')[1:], 16)
                if level.get_un_pw():
                    embed.description += level.get_un_pw()
                if level.solutions:
                    embed.add_field(name='Solutions', value='\n'.join([s.text for s in level.solutions]))
                embeds.append(embed)
            await ctx.send(embeds=embeds)
    else:
        await ctx.send(messages.use_in_dms, ephemeral=True)


@recall_command.on_autocomplete('level')
async def recall_autocomplete(ctx, level):
    if ctx.channel.type == nextcord.ChannelType.private:
        start = level or ''
        solved_levels = discord_utils.get_solved_levels(ctx.user.id, start=start)
        await ctx.response.send_autocomplete([l.name for l in solved_levels])
    else:
        await ctx.response.send_autocomplete([messages.use_in_dms])


@client.slash_command('continue', description='List your current levels')
async def continue_command(ctx):
    if ctx.channel.type == nextcord.ChannelType.private:
        current_levels = list(filter(lambda l: l.solutions, discord_utils.get_solvable_levels(ctx.user.id)))
        embed = nextcord.Embed(title='Current Levels')
        embed.colour = int(db.get_setting('embed_color', '#000000')[1:], 16)
        if current_levels:
            level_lines = []
            for level in current_levels:
                level_link = level.get_encoded_link(db.get_setting('auth_in_link') == 'true')
                level_un_pw = f' {level.get_un_pw()}' if level.get_un_pw() else ''
                if level_link:
                    level_lines.append(f'[{level.name}]({level_link}){level_un_pw}')
                else:
                    level_lines.append(f'{level.name}{level_un_pw}')
            embed.description = '\n'.join(level_lines)
        else:
            embed.description = messages.no_current_levels
        await ctx.send(embed=embed)
    else:
        await ctx.send(messages.use_in_dms, ephemeral=True)


@client.slash_command('setsolved', description='Set a user\'s progress to a certain level')
async def setsolved_command(ctx, user: nextcord.User = nextcord.SlashOption('user', 'User', required=True), level=nextcord.SlashOption('level', 'Level name', required=True)):
    guild_id = int(db.get_setting('guild'))
    guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    author = guild.get_member(int(ctx.user.id)) or await guild.fetch_member(int(ctx.user.id))
    if not author or not discord_utils.is_member_admin(author):
        await ctx.send(messages.permission_denied, ephemeral=True)
        return
    member = guild.get_member(int(user.id)) or await guild.fetch_member(int(user.id))
    if not member:
        await ctx.send('invalid member', ephemeral=True)
        return
    target_level = db.session.query(db.Level).where(db.Level.name == level).all()
    if len(target_level) != 1:
        await ctx.send('level not found', ephemeral=True)
        return
    solved_level_names = []
    unlocked_level_names = []
    for parent_level in discord_utils.get_parent_levels_recursively(target_level[0]):
        if parent_level.solutions and not db.session.query(db.UserSolve)\
                .where(and_(db.UserSolve.level_id == parent_level.id, db.UserSolve.user_id == str(member.id))).scalar():
            solved_level_names.append(parent_level.name)
            db.session.add(db.UserSolve(user_id=str(member.id), level=parent_level))
        if parent_level.unlocks and not db.session.query(db.UserUnlock)\
                .where(and_(db.UserUnlock.level_id == parent_level.id, db.UserUnlock.user_id == str(member.id))).scalar():
            unlocked_level_names.append(parent_level.name)
            db.session.add(db.UserUnlock(user_id=str(member.id), level=parent_level))
    db.session.commit()
    solved_level_names_string = f'{len(solved_level_names)} solves ({", ".join(reversed(solved_level_names))})'
    unlocked_level_names_string = f'{len(unlocked_level_names)} unlocks ({", ".join(reversed(unlocked_level_names))})'
    await discord_utils.update_user_roles(str(member.id))
    await discord_utils.update_user_nickname(str(member.id))
    await ctx.send(f'Updated {member.display_name}, added {solved_level_names_string} and {unlocked_level_names_string}', ephemeral=True)


@setsolved_command.on_autocomplete('level')
async def setsolved_autocomplete(ctx, level):
    guild_id = int(db.get_setting('guild'))
    guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    author = guild.get_member(int(ctx.user.id)) or await guild.fetch_member(int(ctx.user.id))
    if not author or not discord_utils.is_member_admin(author):
        levels = []
    else:
        levels = db.session.query(db.Level).where(db.Level.name.startswith(level)).all()
    await ctx.response.send_autocomplete([l.name for l in levels])


@client.slash_command('resetuser', description='Delete a user from the database')
async def resetuser_command(ctx, user: nextcord.User = nextcord.SlashOption('user', 'User', required=True)):
    guild_id = int(db.get_setting('guild'))
    guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    author = guild.get_member(int(ctx.user.id)) or await guild.fetch_member(int(ctx.user.id))
    if not author or not discord_utils.is_member_admin(author):
        await ctx.send(messages.permission_denied, ephemeral=True)
        return
    member = guild.get_member(int(user.id)) or await guild.fetch_member(int(user.id))
    if not member:
        await ctx.send('invalid member', ephemeral=True)
        return
    db_user = db.session.get(db.User, str(member.id))
    if db_user:
        db.session.delete(db_user)
        db.session.commit()
        await discord_utils.update_user_roles(str(member.id))
        await discord_utils.update_user_nickname(str(member.id))
        await ctx.send(f'Deleted {member.display_name} from the database', ephemeral=True)
    else:
        await ctx.send(f'{member.display_name} is not in the database', ephemeral=True)
