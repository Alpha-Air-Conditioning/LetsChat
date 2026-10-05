from django.contrib.auth.models import User

from rest_framework import serializers

from chats.models import Conversation
from chats.models import Message


class UserSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = User

        fields = (
            'id',
            'username',
            'email',
        )


class RegisterSerializer(
    serializers.ModelSerializer
):

    password = serializers.CharField(
        write_only=True,
        min_length=8
    )


    class Meta:

        model = User

        fields = (
            'username',
            'email',
            'password',
        )


    def create(
        self,
        validated_data
    ):

        return User.objects.create_user(

            username=validated_data[
                'username'
            ],

            email=validated_data.get(
                'email',
                ''
            ),

            password=validated_data[
                'password'
            ]

        )


class MessageSerializer(
    serializers.ModelSerializer
):

    sender = UserSerializer(
        read_only=True
    )


    class Meta:

        model = Message

        fields = (
            'id',
            'conversation',
            'sender',
            'content',
            'created_at',
            'is_edited',
            'is_deleted',
        )

        read_only_fields = (
            'id',
            'sender',
            'created_at',
            'is_edited',
            'is_deleted',
        )


    def validate_conversation(
        self,
        conversation
    ):

        user = self.context[
            'request'
        ].user


        if not conversation.participants.filter(
            id=user.id
        ).exists():

            raise serializers.ValidationError(
                'You are not a member of this conversation.'
            )


        return conversation


class ConversationSerializer(
    serializers.ModelSerializer
):

    participants = serializers.PrimaryKeyRelatedField(

        many=True,

        queryset=User.objects.all()

    )


    class Meta:

        model = Conversation

        fields = (
            'id',
            'name',
            'participants',
            'created_by',
            'created_at',
            'updated_at',
        )

        read_only_fields = (
            'id',
            'created_by',
            'created_at',
            'updated_at',
        )


    def create(
        self,
        validated_data
    ):

        participants = validated_data.pop(
            'participants',
            []
        )


        request = self.context[
            'request'
        ]


        conversation = Conversation.objects.create(

            created_by=request.user,

            **validated_data

        )


        conversation.participants.add(
            request.user
        )


        conversation.participants.add(
            *participants
        )


        return conversation